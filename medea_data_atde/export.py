# %% imports
import pandas as pd
import numpy as np
from medea_data_atde.retrieve import hours_in_year


def compile_symbols(root_dir, timeseries, zones, year, invest_conventionals=True, invest_renewables=True,
                    invest_storage=True, invest_tc=True):
    """
    prepares dictionaries used to build input data gdx-files for power system model medea
    :param root_dir: root directory
    :param timeseries: path to timeseries_regional.csv
    :param zones: ISO 2-letter country code for countries to model. Default: ['AT', 'DE']
    :param year: integer of year to model. Default: 2016
    :param invest_conventionals: boolean
    :param invest_renewables: boolean
    :param invest_storage: boolean
    :param invest_tc: boolean for investment in transmission capacity
    :return:
    """
    idx = pd.IndexSlice
    raw_data = root_dir / 'data' / 'raw'
    technologies = {
        'capacity': pd.read_csv(raw_data / 'capacities.csv'),
        'capacity_transmission': pd.read_csv(raw_data / 'transmission.csv', index_col=[0, 1]),
        'technology': pd.read_csv(raw_data / 'technologies.csv').dropna(axis=0, how='all'),
        'operating_region': pd.read_csv(raw_data / 'operating_region.csv', index_col=[0, 1, 2]),
        'mappings': []
    }

    ts_data = {
        'timeseries': pd.read_csv(timeseries, sep=';', decimal=',')
    }

    estimates = {
        ##        'ESTIMATES': pd.read_excel(tech_data, 'ESTIMATES', index_col=[0]),
        'external_cost': pd.read_csv(raw_data / 'external_cost.csv', index_col=[0]),
        #        'AIR_POLLUTION': pd.read_excel(tech_data, 'AIR_POLLUTION', index_col=[0]),
        #        'CO2_INTENSITY': pd.read_excel(tech_data, 'CO2_INTENSITY', index_col=[0]),
        #        'COST_TRANSPORT': pd.read_excel(tech_data, 'COST_TRANSPORT', index_col=[0]),
        ##        'DISCOUNT_RATE': pd.read_excel(tech_data, 'WACC', index_col=[0]),
        #        'DISTANCE': pd.read_excel(tech_data, 'KM', index_col=[0])
    }

    # create SETS
    # --------------------------------------------------------------------------- #
    sets = {
        'e': {carrier: [True] for carrier in np.unique(technologies['technology'][['fuel', 'primary_product']])},
        # all energy carriers
        'i': {input: [True] for input in technologies['technology']['primary_product'].unique()},  # energy inputs
        'f': {final: [True] for final in technologies['technology']['primary_product'].unique()},  # final energy
        't': {tec: [True] for tec in technologies['technology'].index.unique()},  # technologiest
        'c': {chp: [True] for chp in technologies['operating_region'].index.get_level_values(0).unique()},
        # co-generation technologies
        'd': {plant: [True] for plant in technologies['technology'].loc[
            technologies['technology']['conventional'] == 1].index.unique()},  # dispatchable technologies
        'r': {intmit: [True] for intmit in technologies['technology'].loc[
            technologies['technology']['intermittent'] == 1].index.unique()},  # intermittent technologies
        's': {storage: [True] for storage in technologies['technology'].loc[
            technologies['technology']['storage'] == 1].index.unique()},  # storage technologies
        'g': {transmit: [True] for transmit in technologies['technology'].loc[
            technologies['technology']['transmission'] == 1].index.unique()},  # transmission technologies
        'l': {f'l{x}': [True] for x in range(1, 5)},  # feasible operating regions
        'h': {f'h{hour}': [True] for hour in range(1, hours_in_year(year) + 1)},  # time steps / hours
        'z': {zone: [True] for zone in zones}  # market zones
    }

    # convert set-dictionaries to DataFrames
    for key, value in sets.items():
        sets.update({key: pd.DataFrame.from_dict(sets[key], orient='index', columns=['Value'])})

    # create PARAMETERS
    # --------------------------------------------------------------------------- #

    # --------------------------------------------------------------------------- #
    # ** process technology data **
    # amend plant data by co-generation fuel need
    technologies['operating_region']['fuel_need'] = technologies['operating_region']['fuel'] / \
                                                    technologies['technology'].loc[
                                                        technologies['technology'][
                                                            'heat_generation'] == 1, 'eta_ec']
    # transmission distances
    technologies['distance'] = technologies['capacity_transmission']['distance'].loc[
                               technologies['capacity_transmission']['distance'].index.get_level_values(0).str.contains(
                                   '|'.join(zones)) &
                               technologies['capacity_transmission']['distance'].index.get_level_values(1).str.contains(
                                   '|'.join(zones)), :]
    # transmission capacities
    technologies.update({'capacity_transmission': technologies['capacity_transmission']['ATC'].loc[
                                                  technologies['capacity_transmission']['ATC'].index.get_level_values(
                                                      0).str.contains('|'.join(zones)) &
                                                  technologies['capacity_transmission']['ATC'].index.get_level_values(
                                                      1).str.contains('|'.join(zones)), :] / 1000})

    # process time series data
    # --------------------------------------------------------------------------- #

    # date-time conversion and selection
    ts_data['timeseries']['DateTime'] = pd.to_datetime(ts_data['timeseries']['DateTime'])
    ts_data['timeseries'].set_index('DateTime', inplace=True)
    # constrain data to scenario year
    ts_data['timeseries'] = ts_data['timeseries'].loc[
        (pd.Timestamp(year, 1, 1, 0, 0).tz_localize('UTC') <= ts_data['timeseries'].index) &
        (ts_data['timeseries'].index <= pd.Timestamp(year, 12, 31, 23, 0).tz_localize('UTC'))]
    # drop index and set index of df_time instead
    if len(ts_data['timeseries']) == len(sets['h']):
        ts_data['timeseries'].set_index(sets['h'].index, inplace=True)
    else:
        raise ValueError('Mismatch of time series data and model time resolution. Is cfg.year wrong?')
    # subset of zonal time series
    ts_data['ZONAL'] = ts_data['timeseries'].loc[:, ts_data['timeseries'].columns.str.startswith(tuple(zones))].copy()
    ts_data['ZONAL'].columns = ts_data['ZONAL'].columns.str.split('-', expand=True)
    # adjust column naming to reflect proper product names ('el' and 'ht')
    ts_data['ZONAL'] = ts_data['ZONAL'].rename(columns={'power': 'el', 'heat': 'ht'})

    # process DEMAND
    ts_data['timeseries']['DE-power-load'] = ts_data['timeseries']['DE-power-load'] / 0.91
    # for 0.91 scaling factor see
    # https://www.entsoe.eu/fileadmin/user_upload/_library/publications/ce/Load_and_Consumption_Data.pdf
    # TODO: check scaling factor

    # process PRICES
    # create price time series incl transport cost
    ts_data['timeseries'].loc[:, 'Nuclear'] = 3.5
    ts_data['timeseries'].loc[:, 'Lignite'] = 4.5
    ts_data['timeseries'].loc[:, 'Biomass'] = 6.5
    # TODO:  set prices in input file

    model_prices = ['Coal', 'Oil', 'Gas', 'EUA', 'Nuclear', 'Lignite', 'Biomass', 'price_day_ahead']
    ts_data['price'] = pd.DataFrame(index=ts_data['timeseries'].index,
                                    columns=pd.MultiIndex.from_product([model_prices, zones]))
    for zone in zones:
        for fuel in model_prices:
            if fuel in estimates['COST_TRANSPORT'].index:
                ts_data['price'][(fuel, zone)] = ts_data['timeseries'][fuel] + estimates['COST_TRANSPORT'].loc[
                    fuel, zone]
            else:
                ts_data['price'][(fuel, zone)] = ts_data['timeseries'][fuel]

    # process INFLOWS to hydro storage plants
    hydro_storage = technologies['technology'].loc[(technologies['technology']['storage'] == 1) &
                                                   (technologies['technology']['fuel'] == 'Water')].index
    inflow_factor = technologies['capacity'].loc[idx['Installed Capacity Out', :, year], hydro_storage].T / \
                    technologies['capacity'].loc[idx['Installed Capacity Out', :, year], hydro_storage].T.sum()
    inflow_factor.columns = inflow_factor.columns.droplevel([0, 2])
    ts_inflows = pd.DataFrame(index=list(ts_data['ZONAL'].index),
                              columns=pd.MultiIndex.from_product([zones, sets['s'].index]))
    for zone in list(zones):
        for strg in hydro_storage:
            ts_inflows.loc[:, (zone, strg)] = ts_data['ZONAL'].loc[:, idx[zone, 'inflows', 'reservoir']] * \
                                              inflow_factor.loc[strg, zone]
    ts_data.update({'INFLOWS': ts_inflows})

    # --------------------------------------------------------------------------- #
    # %% peak load and profiles
    # --------------------------------------------------------------------------- #
    """
    estimates.update({'DISTANCE': estimates['DISTANCE'].loc[
        estimates['DISTANCE'].index.str.contains('|'.join(zones)),
        estimates['DISTANCE'].columns.str.contains('|'.join(zones))]})
    """
    ts_data.update({'PEAK_LOAD': ts_data['ZONAL'].loc[:, idx[:, 'el', 'load']].max().unstack((1, 2)).squeeze()})
    peak_profile = ts_data['ZONAL'].loc[:, idx[:, :, 'profile']].max().unstack(2).drop('ror', axis=0, level=1)
    peak_profile.fillna(0, inplace=True)
    ts_data.update({'PEAK_PROFILE': peak_profile})

    # --------------------------------------------------------------------------- #
    # %% limits on investment - long-run vs short-run
    # TODO: set limits to potentials -- requires potentials first
    # --------------------------------------------------------------------------- #
    # SWITCH_INVEST

    invest_limits = {
        'potentials': pd.read_excel(tech_data, 'potentials', index_col=[0]),
        'thermal': pd.DataFrame([float('inf') if invest_conventionals else 0]),
        'intermittent': pd.DataFrame(data=[float('inf') if invest_renewables else 0][0],
                                     index=zones, columns=sets['r'].index),
        'storage': pd.DataFrame(data=[float('inf') if invest_storage else 0][0],
                                index=zones, columns=sets['s'].index),
        'atc': pd.DataFrame(data=[1 if invest_tc else 0][0],
                            index=zones, columns=zones)
    }

    parameters = {
        'AIR_POL_COST_FIX': estimates['external_cost']['fixed cost'].dropna(),
        'AIR_POL_COST_VAR': estimates['external_cost']['variable cost'].dropna(),
        'CAPACITY': technologies['capacity'],
        'CAPACITY_X': technologies['capacity_transmission'],
        'CAPACITY_STORAGE': technologies['capacity'].loc
        [idx['Storage Capacity', zones, year], sets['s'].index],
        'CAPACITY_STORE_IN': technologies['capacity'].loc
        [idx['Installed Capacity In', zones, year], sets['s'].index],
        'CAPACITY_STORE_OUT': technologies['capacity'].loc
        [idx['Installed Capacity Out', zones, year], sets['s'].index],
        'CAPITALCOST': technologies['technology'].loc[:, 'eqacapex_p'].round(4),
        'CAPITALCOST_E': technologies['technology'].loc[sets['s'].index, 'eqacapex_e'],
        'CAPITALCOST_P': technologies['technology'].loc[sets['s'].index, 'eqacapex_p'],
        'CAPITALCOST_X': technologies['technology'].loc[sets['g'].index, 'eqacapex_p'],
        'CO2_INTENSITY': estimates['external_cost']['CO2_intensity'].dropna(),
        # 'CONVERSION': dict_technologies['technology']['eta_ec'],
        'COST_OM_QFIX': technologies['technology']['opex_f'],
        'COST_OM_VAR': technologies['technology']['opex_v'],
        'DEMAND': ts_data['ZONAL'].loc[:, idx[:, :, 'load']].stack((0, 1)).reorder_levels((1, 0, 2)).round(4),
        # 'DISCOUNT_RATE': [],
        'DISTANCE': technologies['distance'],
        'FEASIBLE_INPUT': technologies['operating_region']['fuel'],
        'FEASIBLE_OUTPUT': technologies['operating_region'][['el', 'ht']].droplevel('f').stack(),
        'INFLOWS': ts_data['INFLOWS'].stack((0, 1)).reorder_levels((1, 0, 2)).astype('float').round(4),
        # 'LAMBDA': estimates['LAMBDA'],
        'LIFETIME': technologies['technology']['lifetime'],
        # 'MAP_INPUTS': [],
        # 'MAP_OUTPUTS': [],
        'PEAK_LOAD': ts_data['PEAK_LOAD'],
        'PEAK_PROFILE': ts_data['PEAK_PROFILE'],
        'PRICE_CO2': ts_data['price'].loc[:, idx['EUA', :]].stack().reorder_levels((1, 0)),
        'PRICE': ts_data['price'].drop(['EUA', 'price_day_ahead'], axis=1).stack((0, 1)).reorder_levels
        ((2, 0, 1)).round(4),  # TODO: performance warning
        # 'PRICE_TRADE': [],
        'PROFILE': ts_data['ZONAL'].loc[:, idx[:, :, 'profile']].stack((0, 1)).reorder_levels((1, 0, 2)).round(4),
        # 'SIGMA': estimates['SIGMA'],
        # 'VALUE_NSE': estimates[''],
        'SWITCH_INVEST': invest_limits['thermal'],
    }
    return sets, parameters

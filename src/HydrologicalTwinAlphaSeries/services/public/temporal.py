import os
import re
import time
from datetime import datetime
from os import sep
from typing import List, Union

import numpy as np
import pandas as pd

from HydrologicalTwinAlphaSeries.config.constants import (
    nbRecs,
    paramRecs,
)
from HydrologicalTwinAlphaSeries.domain.Compartment import Compartment


class CacheMissError(FileNotFoundError):
    """Raised when ``load_from_cache`` cannot find the expected ``.npy`` file.

    Indicates a programmer error: ``fetch`` was called without a prior
    ``HydrologicalTwin.load()`` that materialised the on-disk cache.
    """


class Temporal:
    def __init__(self):
        pass

    def readSimDataFromBin(
        self,
        compartment: Compartment,
        outtype: str,
        syear: int,
        eyear: int
    ):

        print("Reading Outputs from binary files")
        total_ndays = (
            datetime.strptime(f"{eyear}-08-01", "%Y-%m-%d")
            - datetime.strptime(f"{syear}-07-31", "%Y-%m-%d")
        ).days - 1

        count_day = 0
        outfolder_path = compartment.out_caw_path
        ncells = compartment.mesh.ncells
        nparams = nbRecs[compartment.compartment + "_" + outtype]

        print(f"Output Caw directory : {outfolder_path}")
        print(f"Numbers of cells in resolution : {ncells}")
        print(f"Numbers of Recs parameters : {nparams}")

        # binary encoding
        dtype = np.dtype(
            [
                ("begin", np.int32),
                ("values", np.float64, (ncells,)),
                ("end", np.int32),
            ]
        )

        # Pre-allocate simMatrix once before the loop
        simMatrix = np.empty((nparams, ncells, total_ndays), dtype=np.float64)

        # read sim data in binary file for every years
        for y in range(syear, eyear):
            print(f"Period reading : {y} - {y+1}")

            ## output file path
            outFileName = (
                outfolder_path
                + sep
                + compartment.compartment
                + "_"
                + outtype
                + "."
                + str(y)
                + str(y + 1)
                + ".bin"
            )
            print(outFileName)

            ## check if the current year is bissextile and return days number
            _, ndays = self.check_bissextile(y + 1)

            ## open binary file
            with open(outFileName, "rb") as file:
                ### read from file with numpy and reshape in a vector
                readata = np.fromfile(file, dtype=dtype)
                readOutNCells = readata[0][0]
                readarray = readata["values"]

            if readOutNCells != ncells:
                print(
                    "WARNING : the number of cells read in the configuration is different from the number of cells in the Caw output : \n"
                    + f"\tNumber of cells reading from configuration : {ncells}\n"
                    + f"\tNumber of cells reading in caw output : {readOutNCells}"
                )
            else:
                print(
                    "Year outfile has been read. Recovering data...", flush=True
                )

            # VECTORIZED: Reshape readarray directly to (ndays, nparams, ncells)
            array_reshaped = readarray.reshape(ndays, nparams, ncells)

            # VECTORIZED: Transpose to (nparams, ncells, ndays) and assign in one operation
            simMatrix[:, :, count_day:count_day + ndays] = array_reshaped.transpose(1, 2, 0)

            print(f"Added values in sim matrix from {count_day} day to {count_day + ndays}")
            count_day += ndays
            print("Done", flush=True)
            print(f"Sim Matrix count {simMatrix.shape[2]} days")

        return simMatrix

    def readSimDataFromBinSteady(
        self,
        compartment: Compartment,
        outtype: str,
        syear: int,
        eyear: int,
    ) -> np.ndarray:
        """Read a steady-state CaWaQS ``.00.bin`` file into shape
        ``(nparams, ncells, total_ndays)``. The daily axis broadcasts the
        single steady snapshot across every simulated day.
        """
        outfolder_path = compartment.out_caw_path
        outFileName = (
            outfolder_path
            + sep
            + compartment.compartment
            + "_"
            + outtype
            + ".00"
            + ".bin"
        )
        ncells = compartment.mesh.ncells
        nparams = nbRecs[compartment.compartment + "_" + outtype]
        total_ndays = (
            datetime.strptime(f"{eyear}-08-01", "%Y-%m-%d")
            - datetime.strptime(f"{syear}-07-31", "%Y-%m-%d")
        ).days - 1

        dtype = np.dtype(
            [
                ("begin", np.int32),
                ("values", np.float64, (ncells,)),
                ("end", np.int32),
            ]
        )
        data = np.fromfile(outFileName, dtype=dtype)

        # Steady outputs hold a single daily snapshot that is broadcast
        # across the whole simulation period.
        daily_values = data["values"][:nparams]  # (nparams, ncells)
        simMatrix = np.broadcast_to(
            daily_values[:, :, np.newaxis],
            (nparams, ncells, total_ndays),
        ).copy()
        return simMatrix

    @staticmethod
    def _cache_filename(
        compartment: Compartment,
        outtype: str,
        param: str,
        syear: int,
        eyear: int,
    ) -> str:
        """Canonical cache filename for a single-parameter ``.npy``."""
        if compartment.regime == "Steady":
            return (
                f"{compartment.compartment}_{outtype}_STEADY_{param}.npy"
            )
        return (
            f"{compartment.compartment}_{outtype}_{syear}{eyear}_{param}.npy"
        )

    @staticmethod
    def _stale_cache_files(
        temp_directory: str,
        compartment: Compartment,
        outtype: str,
        params: List[str],
        syear: int,
        eyear: int,
    ) -> List[str]:
        """Return cache files for this (compartment, outtype) whose encoded
        period does not match (syear, eyear). Only relevant for transient
        projects — steady filenames carry no period.
        """
        if compartment.regime == "Steady":
            return []
        if not os.path.isdir(temp_directory):
            return []
        expected = {
            Temporal._cache_filename(
                compartment, outtype, param, syear, eyear
            )
            for param in params
        }
        prefix = f"{compartment.compartment}_{outtype}_"
        stale: List[str] = []
        for filename in os.listdir(temp_directory):
            if not filename.endswith(".npy"):
                continue
            if not filename.startswith(prefix):
                continue
            if filename in expected:
                continue
            # filenames shaped "{comp}_{outtype}_{syear}{eyear}_{param}.npy"
            # for some other period belong to the same (compartment, outtype)
            # and must be evicted.
            if re.fullmatch(
                rf"{re.escape(prefix)}\d{{8}}_.+\.npy", filename
            ):
                stale.append(filename)
        return stale

    def decode_and_cache(
        self,
        compartment: Compartment,
        outtype: str,
        syear: int,
        eyear: int,
        temp_directory: str,
    ) -> None:
        """Ensure an on-disk ``.npy`` cache exists for every parameter of
        ``(compartment, outtype)`` covering the period ``(syear, eyear)``.

        If the full cache is already present, returns without reading any
        binaries. If one or more parameter files are missing, or if stale
        files from a different period exist, the binaries are decoded once
        and one ``.npy`` per parameter is written. Stale files are deleted
        before decoding.
        """
        params = paramRecs[compartment.compartment + "_" + outtype]
        os.makedirs(temp_directory, exist_ok=True)

        expected_paths = [
            os.path.join(
                temp_directory,
                self._cache_filename(compartment, outtype, param, syear, eyear),
            )
            for param in params
        ]
        if all(os.path.exists(path) for path in expected_paths):
            return

        for stale in self._stale_cache_files(
            temp_directory, compartment, outtype, params, syear, eyear
        ):
            stale_path = os.path.join(temp_directory, stale)
            try:
                os.remove(stale_path)
                print(f"Evicted stale cache file : {stale_path}")
            except OSError:
                pass

        stime = time.time()
        if compartment.regime == "Transient":
            simMatrix = self.readSimDataFromBin(
                compartment, outtype, syear, eyear
            )
        elif compartment.regime == "Steady":
            simMatrix = self.readSimDataFromBinSteady(
                compartment, outtype, syear, eyear
            )
        else:
            raise ValueError(
                f"Unsupported regime '{compartment.regime}' for "
                f"compartment {compartment.compartment}."
            )

        for id_p, para in enumerate(params):
            target = os.path.join(
                temp_directory,
                self._cache_filename(compartment, outtype, para, syear, eyear),
            )
            if not os.path.exists(target):
                np.save(target, simMatrix[id_p])
                print(f"Cached sim data : {target}")

        print(f"DECODE AND CACHE : {time.time() - stime:.2f} seconds")

    def load_from_cache(
        self,
        compartment: Compartment,
        outtype: str,
        param: str,
        syear: int,
        eyear: int,
        temp_directory: str,
    ) -> np.ndarray:
        """Load a single-parameter array from the on-disk cache.

        Raises ``CacheMissError`` if the expected file is absent. A cache
        miss here means ``HydrologicalTwin.load()`` did not run for this
        ``(compartment, outtype)`` — it is a programmer error, not a
        user-facing condition.
        """
        filename = self._cache_filename(
            compartment, outtype, param, syear, eyear
        )
        path = os.path.join(temp_directory, filename)
        if not os.path.exists(path):
            raise CacheMissError(
                f"No cache for ({compartment.compartment}, {outtype}, "
                f"{param}, {syear}-{eyear}) at {path}. "
                "Did HydrologicalTwin.load() run?"
            )
        stime = time.time()
        simMatrix = np.load(path)
        print(f"LOAD FROM CACHE : {time.time() - stime:.2f} seconds ({filename})")
        return simMatrix

    def readObsData(
        self,
        compartment:Compartment,
        id_col_data: int,
        id_col_time: int,
        sdate: str,
        edate: str,
    )-> Union[tuple, None]:
        """
        Reading observation data from .dat file

        :param compartment: compartment object
        :type compartment: Compartment
        :param id_col_data: id of column containing measurements
        :type id_col_data: int
        :param id_col_time: id of column containing time vector (in caw day format)
        :type id_col_time: int
        :param sdate: Simulation starting year simulation
        :type sdate: str
        :param edate: Simulation ending year
        :type edate: str
        :return: Tuple of (data, dates, point_ids) where data has shape
            (n_points, n_timesteps) with NaN for missing values,
            dates is a datetime64[D] array, and point_ids is a list.
            Returns None if observation directory is not defined.
        :rtype: Union[tuple, None]

        .. WARNING::
            The file must not contain column header and sep should be \\s+
        """
        print("READING OBS DATA", flush=True)
        print(f"Starting sim date : {str(sdate)}", flush=True)
        print(f"Ending sim date : {str(edate)}", flush=True)

        def getObsDataPath(obs_directory, obs_name)->Union[str, None]:
            if obs_path == '' :
                print("Observation directory is not defined. No obs data will be read.")

                return None
            else :
                path = None

                for root, dirs, files in os.walk(obs_directory):
                    if str(obs_name) + ".dat" in files :
                        path =  os.path.join(root, obs_name + ".dat")

                if path is None :
                    raise FileNotFoundError(f"File {obs_name}.dat hasn't been found in {obs_directory}")
                else :
                    return path

        stime = time.time()
        obs_path = compartment.obs_path  # observation data path
        obs_obj = compartment.obs  # observation object

        # list ids of observations points
        obs_points = obs_obj.obs_points
        sdate_str = str(sdate) + "-08-01"
        edate_str = str(edate) + "-07-31"

        # Generate date array as numpy datetime64
        dates = np.arange(
            np.datetime64(sdate_str),
            np.datetime64(edate_str) + np.timedelta64(1, 'D'),
            dtype='datetime64[D]'
        )
        n_days = len(dates)

        point_ids = []
        point_data_list = []

        # read record data from obs directory
        for obs_point in obs_points:
            print(f'obs point : {obs_point}')
            obs_point_path = getObsDataPath(obs_path, obs_point.id_point)

            if obs_point_path is None :
                return None

            point_ids.append(obs_point.id_point)

            if obs_point_path != '':
                # Use pandas only for robust .dat file parsing
                raw = pd.read_csv(
                    obs_point_path,
                    sep=r"\s+",
                    header=None,
                    index_col=id_col_time,
                    parse_dates=True,
                )
                obs_values = raw[id_col_data].values.astype(np.float64)
                obs_dates = raw.index.values.astype('datetime64[D]')

                # Allocate NaN row, fill matching dates via searchsorted
                row = np.full(n_days, np.nan)
                indices = np.searchsorted(dates, obs_dates)
                valid = indices < n_days
                valid[valid] &= dates[indices[valid]] == obs_dates[valid]
                row[indices[valid]] = obs_values[valid]
                point_data_list.append(row)

            else :
                print(f'Warning : {obs_point.name} hasn\'t been found in observation data folder.')
                point_data_list.append(np.full(n_days, np.nan))

        data = np.vstack(point_data_list)  # shape (n_points, n_timesteps)

        print(f'OBS DATA shape : {data.shape}')
        etime = time.time()
        print(f"READING OBS DATA : {etime - stime} seconds")
        return data, dates, point_ids


    def readSimSteady(self, compartment) :
        print('READING SIM DATA')
        # simulated dataframe initialisation
        dfSim = pd.DataFrame(index = [0])

        # reading correspond file
        correspFile = pd.read_csv(os.path.join(
            compartment.out_caw_directory, 'AQ_param_overview.txt',
            ), sep=r'\s+')

        # Reading Hend file for each aq layer
        for layerName in compartment.layers_gis_names :
            simdata = pd.read_csv(os.path.join(
                compartment.out_caw_directory,
                f'Hend_{layerName}.txt'
                ), header=None, sep=r'\s+', index_col=0)

            ## reverse inderx and columnes
            simdata = simdata.T
            simdata.index = [0]

            id_layer = compartment.layers_gis_names.index(layerName) + 1
            correspLayer = correspFile.loc[correspFile['ID_LAYER'] == id_layer]
            simdata = simdata.rename(columns = {k:v for k, v in zip(correspLayer['ID_INTERN'].values, correspLayer['ID_ABS'].values)})
            dfSim = pd.concat([dfSim, simdata], axis = 1)



        return dfSim

    def readObsSteady(self,
                      compartment:Compartment,
                      id_col_time:int,
                      id_col_data:int,
                      obs_aggr:Union[str,float],
                      obs_point=None,
                      cutsdate=None,
                      cutedate=None)->pd.DataFrame:
        """
        Reading steady observation function

        Translate a temporal chronicle to steady chronicle

        :param compartment: Hydrological compartiment object
        :type compartment: Compartment
        :param id_col_time: columns id containing time vector in observed data
        :type id_col_time: int
        :param id_col_data: columns id containing data vector in observed data
        :type id_col_data: int
        :return: Dataframe countaining observed values (index : [0], columns : mesurement point id)
        :rtype: pd.DataFrame
        """
        print("READING OBS DATA", flush=True)

        def getObsDataPath(obs_directory, obs_name)->str:
            for parent_folder, child_folder, files in os.walk(obs_directory):
                if obs_name + ".dat" in files:
                    path = os.path.join(parent_folder, obs_name + ".dat")
                    print(f'Path of observed data : {path}')
                    return path
                else :
                    print(f'WARNING : {obs_name} hasn\'t be found in given recorded data folder.')
                    return ''

        stime = time.time()
        obs_path = compartment.obs_path  # observation data path
        obs_obj = compartment.obs  # observation object

        # list ids of observations points
        obs_points = obs_obj.obs_points

        # init mesurement dataframe which contain all observation time series
        mesurements = pd.DataFrame(
            index=[0]
        )

        if obs_point is None :
            # read record data from obs directory
            for obs_point in obs_points:
                print(f'obs point : {obs_point}')
                obs_point_path = getObsDataPath(obs_path, obs_point.id_cell)
                # print(f'path : {obs_point_path}')
                if obs_point_path != '':
                    data = pd.read_csv(
                        obs_point_path,
                        sep=r"\s+",
                        header=None,
                        index_col=id_col_time,
                        parse_dates=True,
                    )
                    # extract recorded data
                    data = data[[id_col_data]]

                    if cutsdate is not None and cutedate is not None:
                        data = data.loc[cutsdate:cutedate]
                        print(f'Reading observation periode : {cutsdate} - {cutedate}')
                    else :
                        print('Observation chronicles are read in full')

                    if obs_aggr == 'mean' :
                        data = data.mean()
                    elif obs_aggr == 'min' :
                        data = data.min()
                    elif obs_aggr == 'max' :
                        data = data.max()
                    else :
                        data = data.quantile(obs_aggr)

                    data = pd.DataFrame(data)
                    # chance index col for id od mp
                    data.columns = [obs_point.id_cell]
                    data.index = [0]
                    # ­data = data.loc[sdate : edate]
                    # add recorded data to mesurement dataframe

                    mesurements.loc[0, obs_point.id_cell] = data.loc[0, obs_point.id_cell]
        else :
            print(f'obs point : {obs_point}')
            obs_point_path = getObsDataPath(obs_path, obs_point.id_cell)
            # print(f'path : {obs_point_path}')
            if obs_point_path != '':
                data = pd.read_csv(
                    obs_point_path,
                    sep=r"\s+",
                    header=None,
                    index_col=id_col_time,
                    parse_dates=True,
                )
                # extract recorded data
                data = data[[id_col_data]]

                if obs_aggr == 'mean' :
                    data = data.mean()
                elif obs_aggr == 'min' :
                    data = data.min()
                elif obs_aggr == 'max' :
                    data = data.max()
                else :
                    data = data.quantile(obs_aggr)

                data = pd.DataFrame(data)
                # chance index col for id od mp
                data.columns = [obs_point.id_cell]
                data.index = [0]
                # ­data = data.loc[sdate : edate]
                # add recorded data to mesurement dataframe

                mesurements[obs_point.id_cell] = data[obs_point.id_cell]


        print(f'MESUREMENTS : {mesurements}')
        etime = time.time()
        print(f"READING OBS DATA : {etime - stime} seconds")
        # return obs dataframe
        return mesurements

    def check_bissextile(self, year:int)->(bool, int):
        """Check if the given year is bissextile

        :param year: Year to check
        :type year: int
        :return: True if its a bissextile year, False if not. The number of day in the year is given too
        :rtype: (bool, int)
        """

        if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0):
            return (True, 366)
        else:
            return (False, 365)

    def simMatrixToDf(
        self,
        matrix:np.array,
        sdate:str,
        edate:str,
        cutsdate:str=None,
        cutedate:str=None,
        cell_ids=None
        )->pd.DataFrame:
        """_summary_

        :param matrix: Simulated matrix
        :type matrix: np.array
        :param sdate: Starting date of the simulation (format : %Y/%M/%d)
        :type sdate: str
        :param edate: Ending date of the simulation (format : %Y/%M/%d)
        :type edate: str
        :param cutsdate:  Starting date of the desired exctractionPeriod, defaults to None (format : %Y/%M/%d)
        :type cutsdate: str, optional
        :param cutedate: Ending date of the desired exctractionPeriod, defaults to None (format : %Y/%M/%d)
        :type cutedate: str, optional
        :return: Simulated Dataframe
        :rtype: pd.DataFrame
        """


        print("Convert SimMatrix in numpy format to dataframe")

        dates = pd.date_range(start=f'{sdate}-08-01', end=f'{edate}-07-31')

        if cell_ids is not  None:
            df_sim = pd.DataFrame(
                matrix.T,
                index=dates,
                columns=cell_ids
            )
        else :
            df_sim = pd.DataFrame(
                matrix.T,
                index=dates,
                columns=[i for i in range(1, matrix.shape[0] + 1)],
            )

        if cutedate is not None and cutsdate is not None:
            print(f"Return period : {cutsdate} - {cutedate}")
            df_sim = df_sim.loc[cutsdate:cutedate]

        print("Done")
        print(df_sim.head(), flush=True)
        return df_sim


    def aggregate_matrix(
        self,
        df:pd.DataFrame,
        agg_dimension:Union[str, float],
        fz:str,
        plurianual_agg:bool,
        compartment:Compartment=None
    ) -> pd.DataFrame:
        """
        Aggragate given matrix according specified aggragator on a specied matrix
        dimension

        Paremeters :
        :param df: time series wanted to be aggragate (meshes, recorded parameter, nday)
        :param aggragator: mean or interanual
        :param agg_dimention: set 1 to agregate on time
        :param syear: Starting year of the simulation
        :param eyear: Ending year of the simulation
        :return: Aggragated matrix (columns : id_abs, index : dates)
        :rtype: pd.DataFrame
        """
        print("Aggragate Sim Matrix...", flush=True)
        print("\tAggragator : ", agg_dimension, flush=True)
        print("\tFz : ", fz, flush=True)
        print("\tPlurianual Agg : ", plurianual_agg, flush=True)

        if fz == 'Annual':
            if agg_dimension == "sum":
                    df =  pd.DataFrame(df.resample("A-AUG").sum())

            elif agg_dimension == "mean":
                    df = pd.DataFrame(df.resample("A-AUG").mean())

            elif agg_dimension == "min":
                    df =  pd.DataFrame(df.resample("A-AUG").min())

            elif agg_dimension == "max":
                    df =  pd.DataFrame(df.resample("A-AUG").max())

            elif agg_dimension == "quantile" :
                df = df.quantile(q = agg_dimension, axis = 0)

            df.index = df.index.strftime('%Y')

            if plurianual_agg is True :
                df = pd.DataFrame(df.mean()).T
                df.index = ["Z(x, y)"]


        if fz == 'Monthly' and plurianual_agg:
            if agg_dimension == "sum":
                df = df.resample("M").sum()

            elif agg_dimension == "mean":
                df = df.resample("M").mean()

            elif agg_dimension == "min":
                df = df.resample("M").min()

            elif agg_dimension == "min":
                df = df.resample("M").min()

            elif agg_dimension == "quantile" :
                df = df.quantile(agg_dimension, axis = 0)

            df.index = df.index.strftime('%m-%Y')

            if plurianual_agg is True :
                df.index = pd.to_datetime(df.index).strftime('%m')
                df = df.groupby(df.index).mean()

        print(df, flush=True)
        print("Done", flush=True)

        return df

    # Seconds in one day — the m³/s → m³/day conversion folded into the monthly
    # sum below. Kept local (not a magic number spread across the method) so the
    # "per-day volume, then summed over the month" definition reads in one place.
    _SECONDS_PER_DAY = 86400.0

    def monthly_total_volume(
        self,
        arr: np.ndarray,
        dates: np.ndarray,
    ) -> (np.ndarray, np.ndarray):
        """Sum a daily ``m³/s`` series into a calendar-month **total volume** (m³).

        This is the plain per-month ``resample("M").sum()`` that
        :meth:`aggregate_matrix`'s monthly branch never exposes on its own: that
        branch is gated behind ``plurianual_agg``, relabels the index to
        ``'%m-%Y'``, and can collapse to a pluriannual mean — none of which is a
        single self-contained "volume that crossed this month" total. This method
        is the dedicated primitive for that quantity, so bending the gated branch
        (and risking its existing callers) is not needed.

        For each series the monthly value for month *m* is
        ``Σ_{d ∈ days(m)} value_d × 86400`` (m³): the ``×86400`` m³/s→per-day
        volume conversion is folded in **before** the sum, so summing over the
        month's real simulated days naturally honours 28/29/30/31-day months and
        totals a partial start/end month over only its simulated days (the true
        volume over the simulated portion, not an error).

        :param arr: Daily series, shape ``(n_days,)`` (a single face series) or
            ``(n_days, n_series)`` (a column per series). Time is axis 0, aligned
            row-for-row with ``dates``.
        :param dates: 1-D array of daily ``datetime64`` (or anything
            ``pd.to_datetime`` accepts), one per row of ``arr``.
        :returns: ``(monthly_matrix, monthly_index)`` where ``monthly_matrix`` has
            the same trailing shape as ``arr`` (``(n_months,)`` for a 1-D input,
            ``(n_months, n_series)`` for 2-D) and ``monthly_index`` is a 1-D array
            of stable, parseable ``YYYY-MM`` month labels — one per calendar month
            present in ``dates``, in ascending order.
        :rtype: (np.ndarray, np.ndarray)
        """
        arr = np.asarray(arr, dtype=float)
        was_1d = arr.ndim == 1
        if was_1d:
            arr = arr[:, np.newaxis]

        index = pd.to_datetime(np.asarray(dates))
        df = pd.DataFrame(arr * self._SECONDS_PER_DAY, index=index)

        # Plain calendar-month sum — one row per (year, month) actually present,
        # NO pluriannual collapse and NO '%m-%Y' relabel (cf. aggregate_matrix).
        monthly = df.resample("M").sum()

        # Stable, parseable month labels (period end → its own year-month), so the
        # loose CSV and the GeoPackage can be read back without ambiguity.
        monthly_index = monthly.index.strftime("%Y-%m").to_numpy()
        monthly_matrix = monthly.to_numpy()
        if was_1d:
            monthly_matrix = monthly_matrix[:, 0]

        return monthly_matrix, monthly_index

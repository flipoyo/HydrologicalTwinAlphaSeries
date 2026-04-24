import os
import re
import time
from datetime import datetime, timedelta
from os import sep
from typing import Union

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.strtree import STRtree

# plotly.offline.init_notebook_mode()
# display(HTML(
#     '<script type="text/javascript" async src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.1/MathJax.js?config=TeX-MML-AM_SVG"></script>'
# ))
from HydrologicalTwinAlphaSeries.config.constants import (
    nbRecs,
    paramRecs,
)
from HydrologicalTwinAlphaSeries.domain.Compartment import Compartment
from HydrologicalTwinAlphaSeries.tools.spatial_utils import get_nearest_row

# Import simobs
"""
simsobs_path = os.environ.get("simobs")
if simsobs_path :
    try :
        sys.path.append(simsobs_path)
        from simobs import Mod_Station, Mod_Piezo

    except ImportError as e :
        print(f"Importation erreur : verifie environnement path of simobs")
"""


class Manage:
    class Budget:
        def __init__(self):
            pass

        def calcInteranualBVariableNumpy(
            self, 
            data: np.ndarray, 
            param: str, 
            out_folder: str, 
            agg: str, 
            fz: str, 
            sdate: int,
            edate: int,
            cutsdate: str,
            cutedate: str,
            pluriannual: bool = False
        ) -> tuple:
            """
            Calculate interannual budget of a hydrological variable using NumPy.

            :param data: NumPy array of simulated hydrological variables.
                        Format: shape (n_timesteps, n_cells)
            :type data: np.ndarray
            :param param: hydrological variable name
            :param out_folder: output folder name where outputs are written
            :type out_folder: str
            :param agg: aggregation type (mean, sum, max, min)
            :type agg: str
            :param fz: frequency of aggregation (Y, M, D)
            :type fz: str
            :param sdate: start year
            :type sdate: int
            :param edate: end year
            :type edate: int
            :param cutsdate: cut start date (format: 'YYYY-MM-DD')
            :type cutsdate: str
            :param cutedate: cut end date (format: 'YYYY-MM-DD')
            :type cutedate: str
            :param pluriannual: pluriannual aggregation
            :type pluriannual: bool
            :return: Tuple of (aggregated_data, date_labels)
            :rtype: tuple
            """
            print("Calculate Interannual Budget (NumPy)")
            print(f"Aggregation type : {agg}")
            print(f"Frequency : {fz}")
            print(f'Pluriannual : {pluriannual}')
            
            # Spatial aggregation: mean across all cells
            # data shape is (ncells, ndays), so axis=0 averages across cells → (ndays,)
            data_spatial_mean = np.mean(data, axis=0)
            
            # Generate date range
            start_date = datetime.strptime(cutsdate, "%Y-%m-%d")
            end_date = datetime.strptime(cutedate, "%Y-%m-%d")
            n_days = (end_date - start_date).days + 1
            dates = np.array([start_date + timedelta(days=i) for i in range(n_days)])
            
            # Ensure data length matches dates
            if len(data_spatial_mean) != len(dates):
                min_len = min(len(data_spatial_mean), len(dates))
                data_spatial_mean = data_spatial_mean[:min_len]
                dates = dates[:min_len]
            
            # Define aggregation function
            agg_funcs = {
                'mean': np.mean,
                'sum': np.sum,
                'max': np.max,
                'min': np.min
            }
            agg_func = agg_funcs.get(agg, np.mean)
            
            # Temporal aggregation based on frequency
            if fz == 'Y' and not pluriannual:
                # Yearly aggregation (one bar per year)
                years = np.array([d.year for d in dates])
                unique_years = np.unique(years)
                aggregated_data = np.array([
                    agg_func(data_spatial_mean[years == year])
                    for year in unique_years
                ])
                date_labels = unique_years.astype(str)

            elif fz == 'Y' and pluriannual:
                # Yearly pluriannual: aggregate each year, then average across years
                years = np.array([d.year for d in dates])
                unique_years = np.unique(years)
                yearly_values = np.array([
                    agg_func(data_spatial_mean[years == year])
                    for year in unique_years
                ])
                aggregated_data = np.array([np.mean(yearly_values)])
                date_labels = np.array([f"Mean {unique_years[0]}-{unique_years[-1]}"])
                
            elif fz == 'M' and not pluriannual:
                # Monthly aggregation (each month separately)
                year_months = np.array([d.strftime('%Y-%m') for d in dates])
                unique_year_months = np.unique(year_months)
                aggregated_data = np.array([
                    agg_func(data_spatial_mean[year_months == ym]) 
                    for ym in unique_year_months
                ])
                date_labels = unique_year_months
                
            elif fz == 'M' and pluriannual:
                # Monthly aggregation (same month across years)
                months = np.array([d.month for d in dates])
                month_names = ['January', 'February', 'March', 'April', 'May', 'June',
                            'July', 'August', 'September', 'October', 'November', 'December']
                
                # Group by month and calculate mean across years
                unique_months = np.unique(months)
                aggregated_data = np.array([
                    np.mean([agg_func(data_spatial_mean[(months == month) & 
                            (np.array([d.year for d in dates]) == year)])
                            for year in np.unique([d.year for d in dates])
                            if np.any((months == month) & (np.array([d.year for d in dates]) == year))])
                    for month in unique_months
                ])
                date_labels = np.array([month_names[m-1] for m in unique_months])
                
            elif fz == 'D' and not pluriannual:
                # Daily (no aggregation)
                aggregated_data = data_spatial_mean
                date_labels = np.array([d.strftime('%Y-%m-%d') for d in dates])
                
            elif fz == 'D' and pluriannual:
                # Daily aggregation (same day across years)
                day_of_year = np.array([d.strftime('%m-%d') for d in dates])
                unique_days = np.unique(day_of_year)
                aggregated_data = np.array([
                    agg_func(data_spatial_mean[day_of_year == day])
                    for day in unique_days
                ])
                date_labels = unique_days
                
            else:
                raise ValueError('Aggregation type not recognized. Please choose between Y, M or D')
            
            print(f"Aggregated shape: {aggregated_data.shape}")
            print(f"Date labels shape: {date_labels.shape}")
            
            return aggregated_data, date_labels, param

        def calcInteranualHVariableNumpy(
            self,
            data: np.ndarray,
            dates: np.ndarray,
            compartment,
            output_folder: str,
            output_name: str
        ) -> tuple:
            """
            Calculate hydrological regime using NumPy arrays.

            :param data: simulated data array (shape: n_timesteps x n_cells)
            :type data: np.ndarray
            :param dates: array of datetime objects corresponding to data timesteps
            :type dates: np.ndarray
            :param compartment: compartment object
            :param output_folder: output folder directory where data will be exported
            :type output_folder: str
            :param output_name: output file name
            :type output_name: str
            :return: Tuple of (aggregated_data, obs_point_names, month_labels)
            :rtype: tuple
            """
            print(
                f"Calculate Interannual Hydrological Regime for {compartment.compartment} compartment",
                flush=True,
            )
            
            # Get observation points
            obs_points = [obs_point for obs_point in compartment.obs.obs_points]
            
            # Extract data for each observation point
            obs_point_data = []
            obs_point_names = []
            
            for obs_point in obs_points:
                # Extract column for this observation point
                cell_data = data[obs_point.id_cell-1,:]
                obs_point_data.append(cell_data)
                obs_point_names.append(f"{obs_point.name} - {obs_point.id_cell}")
            
            # Stack all observation points as rows (shape: n_obs_points x n_timesteps)
            # this matches sim_matrix convention: rows = cells (obs points), columns = days
            obs_data_array = np.vstack(obs_point_data)
            
            # Monthly resampling
            # Extract year and month from datetime64 arrays
            years = dates.astype('datetime64[Y]').astype(int) + 1970
            months = dates.astype('datetime64[M]').astype(int) % 12 + 1
            
            # Create year-month combinations
            year_months = np.array([f"{y:04d}-{m:02d}" for y, m in zip(years, months)])
            unique_year_months = np.unique(year_months)
            
            # Calculate monthly means
            monthly_data = []
            for ym in unique_year_months:
                # mask over time (days); obs_data_array has days on axis 1
                mask = year_months == ym
                monthly_mean = np.mean(obs_data_array[:, mask], axis=1)  # mean over selected days -> per-obs value
                monthly_data.append(monthly_mean)
            
            monthly_data = np.array(monthly_data)  # shape: (n_months, n_obs_points)
            
            # Extract month names for grouping
            month_names_order = ['January', 'February', 'March', 'April', 'May', 'June',
                                'July', 'August', 'September', 'October', 'November', 'December']
            
            monthly_months = np.array([int(ym.split('-')[1]) for ym in unique_year_months])
            
            # Group by month (average across years)
            unique_months = np.unique(monthly_months)
            interannual_data = []
            month_labels = []
            
            for month_num in unique_months:
                mask = monthly_months == month_num
                month_mean = np.mean(monthly_data[mask, :], axis=0)
                interannual_data.append(month_mean)
                month_labels.append(month_names_order[month_num - 1])
            
            interannual_data = np.array(interannual_data)  # shape: (12, n_obs_points)
            month_labels = np.array(month_labels)
            
            # Save to fixed-width text table (human-readable without any software)
            txt_path = output_folder + sep + compartment.compartment + "_" + output_name + ".txt"

            # Compute column widths: max of header name vs formatted value width
            val_width = 10  # width for "XXXXXXXXX" style floats (e.g. "  1234.56")
            col_widths = [max(len(name), val_width) for name in obs_point_names]
            month_col_width = max(len("Month"), max(len(m) for m in month_labels))

            with open(txt_path, 'w') as f:
                # Header row
                header_cells = [name.center(w) for name, w in zip(obs_point_names, col_widths)]
                f.write("Month".ljust(month_col_width) + "  " + "  ".join(header_cells) + "\n")
                # Data rows
                for i, month_label in enumerate(month_labels):
                    val_cells = [f'{val:>{w}.3f}' for val, w in zip(interannual_data[i, :], col_widths)]
                    f.write(month_label.ljust(month_col_width) + "  " + "  ".join(val_cells) + "\n")

            print(f"Saved to: {txt_path}")
            print("Done", flush=True)
            
            return interannual_data, obs_point_names, month_labels


        def calcSimRunoffRatio(self, surf_surf_area:list, catch_surf_area:list, id_surf_mesh:list, matrixRunOff:np.array, matrixRain:np.array, matrixEtr:np.array)->float:
            """Calculated Simulated Runoff ratio

            :param catch_surf_area: list of intersect catchement and surface cell area
            :type catch_surf_area: list
            :param id_surf_mesh: list of ID of cell of the surface resolution
            :type id_surf_mesh: list
            :param matrixRunOff: RunOff daily matrix
            :type matrixRunOff: np.array
            :param matrixRain: Rain daily matrix
            :type matrixRain: np.array
            :return: Runoff ration coefficient
            :rtype: float
            """
            print("RATION RUNOFF/RAIN CALCULATION ...")
            pe = 0
            runoff = 0
                        
            for s_inter, s_surf, id_mesh in zip(catch_surf_area, surf_surf_area, id_surf_mesh):
                # print(f"id catch : {s['ID_CATCH']} - id surf cell : {id_surf_mesh}")
                # s_inter = s["SURF_INTER"]
                rain = np.nansum(matrixRain[id_mesh - 1]) * (s_inter/s_surf)
                etr = np.nansum(matrixEtr[id_mesh - 1]) * (s_inter/s_surf)
                pe += rain - etr
                
                r = (
                    np.nansum(matrixRunOff[id_mesh - 1]) 
                ) * (s_inter/s_surf)
                runoff += r
                
                print(f'Ratio surf surf inter : {(s_inter/s_surf)}')
                print(f'rain : {rain}')
                print(f'etr : {etr}')
                print(f'runoff : {r}')
                
            Qr = runoff / pe
            # print(f"Run_off coeff : {Qr}")
            
            print(f'ID Cells : {id_surf_mesh}\nSimulated run-off:{runoff}\nPe : {pe}\nQr : {Qr}\nCumulativ Surface : {sum(catch_surf_area)}')

            return Qr

        def calcObsRunoffRatio(self, catch_surf_area:list, id_surf_mesh:list, matrixRain:np.array, Obsdata:np.array)->float: 
            """
            Calculated Observed Runoff ratio

            :param catch_surf_area: list of intersect catchement and surface cell area
            :type catch_surf_area: list
            :param id_surf_mesh: list of ID of cell of the surface resolution
            :type id_surf_mesh: list
            :param matrixRain: Rain daily matrix
            :type matrixRain: np.array
            :param Obsdata: Observated daily discharge matrix 
            :type Obsdata:np.array
            :return: Runoff ration coefficient
            :rtype: float
            """
            rain = 0

            for s, id_mesh in zip(catch_surf_area, id_surf_mesh):
                # print(f"id catch : {s['ID_CATCH']} - id surf cell : {id_surf_mesh}")
                # s_inter = s["SURF_INTER"]
                rain += np.nansum(matrixRain[id_mesh - 1]) * (24 * 3600) * s * 1e-6

            runoff = np.nansum(Obsdata) * np.nansum(catch_surf_area)
                
            Qr = runoff / rain
            # print(f"Run_off coeff : {Qr}")
            
            print(f'Observed run-off:{runoff}\nrain : {rain}\nQr : {Qr}')

            return Qr


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

        def checkTempFile(self, temp_dir, compartment, outtype, param) -> Union[tuple[int, int, str], None]:
                # list all numpy file in temp directory
                pattern = re.compile(rf"{compartment.compartment}_{outtype}_(\d{{8}})_{param}.npy")
                

                for filename in os.listdir(temp_dir):
                    if filename.endswith(".npy"):
                        match = pattern.search(filename)
                        if match:
                            dates = match.group(1) 

                            return int(dates[:4]), int(dates[4:]), filename
                
                else : 
                    print("No temporary file found")
                    return None

        def readSimData(
            self,
            compartment:Compartment,
            outtype:str,
            param:str,
            id_layer,
            syear:int,
            eyear:int,
            list_surf=[],
            list_point=None,
            tempDirectory=None,
        )->np.array:


            if compartment.regime == 'Transient':
                stime = time.time()
                
                end = datetime(eyear, 7, 31)
                start = datetime(syear, 8, 1)
                total_ndays = (end - start).days - 1

                print(f"Simulated period count {total_ndays} days")
                
                check_temp_file = self.checkTempFile(
                    tempDirectory,
                    compartment, 
                    outtype, 
                    param
                    )

                if check_temp_file is not None :
                    start_temp_year , end_temp_year, temp_file_name = check_temp_file
                    temp_file_path = os.path.join(tempDirectory, temp_file_name)

                    print(
                        f"Sim Matrix has already been read. Get it form .npy file : {temp_file_path}"
                    )
                    try :
                        simMatrix = np.load(temp_file_path)
                        etime = time.time()
                        print(f"READING SIM DATA : {etime - stime} seconds")

                    
                    except Exception: 
                        os.remove(temp_file_path)
                        print(f"File {temp_file_path} has been removed because of an error, try to read from binary files")

                    if syear < start_temp_year :
                        simMatrixBefore = self.readSimDataFromBin(
                            compartment, outtype, syear, start_temp_year
                        )
                        simMatrixBefore = simMatrixBefore[
                            paramRecs[compartment.compartment + "_" + outtype].index(param)
                        ]

                    if eyear > end_temp_year : 
                        simMatrixAfter = self.readSimDataFromBin(
                            compartment, outtype, end_temp_year, eyear
                        )      
                        simMatrixAfter = simMatrixAfter[
                            paramRecs[compartment.compartment + "_" + outtype].index(param)
                        ]              

                    # concatenate simMatrix
                    if syear < start_temp_year and eyear > end_temp_year :
                        simMatrix = np.hstack((simMatrixBefore, simMatrix, simMatrixAfter))
                        ys = syear
                        ye = eyear
                        os.remove(temp_file_path)
                        temp_file_name = f"{compartment.compartment}_{outtype}_{ys}{ye}_{param}.npy"
                        temp_file_path = os.path.join(tempDirectory, temp_file_name)
                        np.save(temp_file_path, simMatrix)


                    elif syear < start_temp_year and eyear <= end_temp_year :
                        simMatrix = np.hstack((simMatrixBefore, simMatrix))
                        ys = syear
                        ye = end_temp_year
                        os.remove(temp_file_path)
                        temp_file_name = f"{compartment.compartment}_{outtype}_{ys}{ye}_{param}.npy"
                        temp_file_path = os.path.join(tempDirectory, temp_file_name)
                        np.save(temp_file_path, simMatrix)


                    elif syear >= start_temp_year and eyear > end_temp_year :
                        simMatrix = np.hstack((simMatrix, simMatrixAfter))
                        ys = start_temp_year
                        ye = eyear
                        os.remove(temp_file_path)
                        temp_file_name = f"{compartment.compartment}_{outtype}_{ys}{ye}_{param}.npy"
                        temp_file_path = os.path.join(tempDirectory, temp_file_name)
                        np.save(temp_file_path, simMatrix)
                                  
                    return simMatrix

                if check_temp_file is None :
                    
                    simMatrix = self.readSimDataFromBin(
                        compartment, outtype, syear, eyear
                    )
                    
                    for id_p, para in enumerate(
                        paramRecs[compartment.compartment + "_" + outtype]
                    ):
                        temp_file_path = (
                            tempDirectory
                            + sep
                            + compartment.compartment
                            + "_"
                            + outtype
                            + "_"
                            + str(syear)
                            + str(eyear)
                            + "_"
                            + para
                            + ".npy"
                        )
                        if not os.path.exists(temp_file_path):
                            np.save(temp_file_path, simMatrix[id_p])
                            print(f"Saved sim data in : {temp_file_path}")

                    return simMatrix[
                        paramRecs[compartment.compartment + "_" + outtype].index(param)
                        ]
            


            elif compartment.regime == 'Steady' : 
                stime = time.time()
                dtype = dtype = np.dtype(
                        [
                            ("begin", np.int32),
                            ("values", np.float64, (50468,)),
                            ("end", np.int32),
                        ]
                    )
                
                temp_file_path = (
                    tempDirectory
                    + sep
                    + compartment.compartment
                    + "_"
                    + outtype
                    + "_STEADY_"
                    + param
                    + ".npy"
                )


                if os.path.exists(temp_file_path) : 
                    simMatrix = np.load(temp_file_path)
                    etime = time.time()
                    print(f"READING SIM DATA : {etime - stime} seconds")

                    return simMatrix
                
                else : 
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
                    

                    data = np.fromfile(outFileName, dtype=dtype)
                    simMatrix = np.empty(
                                (nparams, ncells, total_ndays), 
                                dtype=np.float64
                                )
                    for nparam in range(nparams):
                        for day in range(total_ndays) : 
                            for n_cell in range(ncells) : 
                                simMatrix[nparam, n_cell, day] = data['values'][nparam][n_cell]
                                
                                
                    
                                
                    etime = time.time()
                    print(f"READING SIM DATA : {etime - stime} seconds")
                    print('Sim matrix has been save in TEMP folder')
                    
                    for id_p, para in enumerate(
                        paramRecs[compartment.compartment + "_" + outtype]
                    ):
                        temp_file_path = (
                            tempDirectory
                            + sep
                            + compartment.compartment
                            + "_"
                            + outtype
                            + "_STEADY_"
                            + param
                            + ".npy"
                        )
                        if not os.path.exists(temp_file_path):
                            np.save(temp_file_path, simMatrix[id_p])
                            print(f"Saved sim data in : {temp_file_path}")
                    return simMatrix[
                        paramRecs[compartment.compartment + "_" + outtype].index(param)
                        ]

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
                

    class Spatial:
        def __init__(self):
            pass

        def getCatchmentCellsIds(
            self,
            obs_point_geom,
            network_gdf: gpd.GeoDataFrame,
            network_col_name_cell: str,
            network_col_name_fnode: str,
            network_col_name_tnode: str,
        ):
            """
            Delineate a catchment by tracing the river network upstream from an observation point.

            Recursively traverses the network topology using node connectivity (fnode/tnode)
            to find all river cells that drain to the given point.

            :param obs_point_geom: Shapely geometry of the observation/outlet point
            :param network_gdf: GeoDataFrame containing the river network segments
            :param network_col_name_cell: Column name for cell IDs in the network layer
            :param network_col_name_fnode: Column name for from-node (upstream node)
            :param network_col_name_tnode: Column name for to-node (downstream node)
            :return: List of cell IDs (int) belonging to the upstream catchment
            """

            list_cprod = []

            # Use cached spatial index via get_nearest_row
            network_first_cell = get_nearest_row(obs_point_geom, network_gdf)
            if network_first_cell is None:
                return list_cprod

            list_cprod.append(network_first_cell[network_col_name_cell])

            direct_up_stream = self.getUpStreamSection(
                network_first_cell,
                network_gdf,
                network_col_name_fnode,
                network_col_name_tnode,
            )
            list_cprod += [cell[network_col_name_cell] for _, cell in direct_up_stream.iterrows()]

            while not direct_up_stream.empty:
                new_upstream = []
                for _, cell in direct_up_stream.iterrows():
                    upstream = self.getUpStreamSection(
                        cell,
                        network_gdf,
                        network_col_name_fnode,
                        network_col_name_tnode,
                    )
                    if not upstream.empty:
                        new_upstream.append(upstream)
                        list_cprod += [c[network_col_name_cell] for _, c in upstream.iterrows()]

                if new_upstream:
                    direct_up_stream = pd.concat(new_upstream, ignore_index=True)
                else:
                    direct_up_stream = gpd.GeoDataFrame()

            return [id_cprod for id_cprod in list_cprod]

        def getUpStreamSection(
            self,
            section,
            network_gdf: gpd.GeoDataFrame,
            network_col_name_fnode: str,
            network_col_name_tnode: str,
        ) -> gpd.GeoDataFrame:
            """
            Get upstream sections from the network.

            :param section: Row representing the current section
            :param network_gdf: GeoDataFrame containing the network
            :param network_col_name_fnode: Column name for from-node
            :param network_col_name_tnode: Column name for to-node
            :return: GeoDataFrame of upstream sections
            """
            fnode = section[network_col_name_fnode]
            return network_gdf[network_gdf[network_col_name_tnode] == fnode]

        def buildAqOutcropping(self, exd, aq_compartment, save=True):
            """
            Identify aquifer cells that outcrop at the land surface.

            Starts with all cells from the topmost layer (layer 0), then adds cells from
            deeper layers whose centroids are not covered by shallower cells. This captures
            areas where older geological formations are exposed at the surface.

            :param exd: ExplorerData instance containing post_process_directory path
            :param aq_compartment: Aquifer Compartment object with mesh attribute
            :param save: If True, saves outcropping cell IDs to OUTPCROOPCELLSLIST.dat
            :return: List of Cell objects (from Mesh.Layer.Cell) that outcrop at surface
            """
            print("Building Outcropping aquifer cells...", flush=True)

            savepath = os.path.join(exd.post_process_directory, "TEMP", "OUTPCROOPCELLSLIST.dat")

            print("\tBuilding outcropping cells")

            mesh = aq_compartment.mesh.mesh
            outcropCells = list(mesh[0].layer)  # Make a copy

            for n_layer, layer in zip(mesh.keys(), mesh.values()):
                count = 0

                if n_layer != 0:
                    # STRtree (Shapely 2.x) replaces a unary_union+contains check:
                    # the union of thousands of polygons dominated runtime, while
                    # a spatial index answers "is this centroid covered?" in O(log N).
                    tree = STRtree([out_cell.geometry for out_cell in outcropCells])

                    for cell in layer.layer:
                        if tree.query(cell.geometry.centroid, predicate="contains").size == 0:
                            outcropCells.append(cell)
                            count += 1

                    print(f"Added {count} cells")

            if save:
                with open(savepath, "w") as f:
                    for cell in outcropCells:
                        f.write(f"{cell.id_abs}\n")

            return outcropCells

        @staticmethod
        def assemble_single_layer_geodataframe(
            agg_df: pd.DataFrame,
            cell_ids: np.ndarray,
            cell_geometries: list,
            crs,
            id_col_name: str = "ID_ELEBU",
        ) -> gpd.GeoDataFrame:
            """Assemble aggregated data + layer geometry into a GeoDataFrame.

            :param agg_df: DataFrame (index=date_labels, columns=cell_ids) from aggregate_for_map
            :param cell_ids: 1D array of cell IDs for the layer
            :param cell_geometries: list of shapely geometries for the layer
            :param crs: pyproj.CRS or EPSG string
            :param id_col_name: column name for the cell ID column
            :return: GeoDataFrame with [id_col, date_columns..., geometry]
            """
            data = agg_df.T.copy()
            data = data.sort_index()
            cols = data.columns.tolist()
            data[id_col_name] = cell_ids.tolist()
            data["geometry"] = cell_geometries
            data = data.sort_values(by=id_col_name)
            data = data[[id_col_name] + cols + ["geometry"]]
            return gpd.GeoDataFrame(data, crs=crs, geometry="geometry")

        @staticmethod
        def assemble_multi_layer_geodataframe(
            agg_df: pd.DataFrame,
            layers: list,
            crs,
            layer_id_offset: int = 0,
        ) -> gpd.GeoDataFrame:
            """Assemble aggregated data + multi-layer geometry into a GeoDataFrame.

            :param agg_df: DataFrame (index=date_labels, columns=cell_ids) from aggregate_for_map
            :param layers: list of LayerInfo objects
            :param crs: pyproj.CRS or EPSG string
            :param layer_id_offset: starting layer ID (0 for MB, 1 for H)
            :return: GeoDataFrame with [ID_ABS, ID_LAY, date_columns..., geometry]
            """
            data = agg_df.T

            cell_ids = []
            layer_ids = []
            geometries = []
            for n_layer, layer_info in enumerate(layers):
                cell_ids.extend(layer_info.cell_ids.tolist())
                layer_ids.extend([n_layer + layer_id_offset] * layer_info.n_cells)
                geometries.extend(layer_info.cell_geometries)

            result = data.loc[cell_ids].copy()
            cols = result.columns.tolist()
            result["ID_ABS"] = cell_ids
            result["ID_LAY"] = layer_ids
            result["geometry"] = geometries
            result = gpd.GeoDataFrame(result, crs=crs, geometry="geometry")
            result = result[["ID_ABS", "ID_LAY"] + cols + ["geometry"]]
            result = result.sort_values(by=["ID_LAY", "ID_ABS"])
            return result

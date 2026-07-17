from datetime import datetime, timedelta
from os import sep

import numpy as np

from HydrologicalTwinAlphaSeries.tools.spatial_utils import require_coupling


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

        # Refuse before the np.vstack below, which would otherwise raise a bare
        # numpy ValueError on the empty list a refused coupling leaves behind.
        require_coupling(
            compartment.obs, context="observation points for hydrological regime"
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

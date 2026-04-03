
from typing import List, Optional, Tuple, Union

import numpy as np

from hydrological_twin_alpha_series.domain.Compartment import Compartment


class Operator:        
    def __init__(self):
        pass

    def _get_agg_func(self, agg: Union[str, float]):
        """Return the numpy aggregation function for the given agg specifier."""
        if isinstance(agg, str):
            agg_funcs = {
                'mean': np.nanmean,
                'sum': np.nansum,
                'min': np.nanmin,
                'max': np.nanmax,
            }
            if agg not in agg_funcs:
                raise ValueError(
                    f"Unknown aggregation: '{agg}'. "
                    f"Use 'mean', 'sum', 'min', 'max', or a float for quantile."
                )
            return agg_funcs[agg]
        elif isinstance(agg, (int, float)):
            return lambda x, axis: np.nanquantile(x, agg, axis=axis)
        else:
            raise TypeError(f"agg must be str or float, got {type(agg)}")

    def t_transform(
        self,
        arr: np.ndarray,
        dates: np.ndarray,
        fz: str,
        agg: Union[str, float] = 'mean',
        year_end_month: int = 12,
        plurianual_agg: bool = False,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Aggregate given matrix over time according to specified frequency.

        Parameters
        ----------
        arr : np.ndarray
            Time series data, shape (n_timesteps, n_locations)
        dates : np.ndarray
            Array of datetime64 objects corresponding to rows in arr
        fz : str
            Frequency: 'Annual', 'Monthly', or 'Daily'
        agg : str or float, optional
            Aggregation function: 'mean', 'sum', 'min', 'max', or a float
            in [0,1] for quantile. Default: 'mean'
        year_end_month : int, optional
            Month at which the fiscal/hydrological year ends (1-12).
            12 = calendar year (Jan-Dec, default).
            8 = hydrological year (Sep-Aug), equivalent to pandas resample("A-AUG").
        plurianual_agg : bool, optional
            If True, perform additional averaging across years/months (default: False)

        Returns
        -------
        Tuple[np.ndarray, np.ndarray]
            Aggregated data array and corresponding date labels
        """
        print("Aggregating time series...", flush=True)
        print("\tFrequency : ", fz, flush=True)
        print("\tAggregation : ", agg, flush=True)
        print("\tPluriannual Agg : ", plurianual_agg, flush=True)

        agg_func = self._get_agg_func(agg)

        if fz == 'Daily':
            date_labels = np.array([str(d) for d in dates])

            if plurianual_agg:
                # Group by day-of-year and average across years
                doy = (dates - dates.astype('datetime64[Y]')).astype(int) + 1
                unique_doy = np.unique(doy)

                aggregated_data = []
                for d in unique_doy:
                    mask = doy == d
                    aggregated_data.append(np.nanmean(arr[mask, :], axis=0))

                arr_agg = np.array(aggregated_data)
                date_labels = np.array([f"DOY-{d:03d}" for d in unique_doy])
            else:
                arr_agg = arr

            print(f"Aggregated shape: {arr_agg.shape}", flush=True)
            print("Done", flush=True)
            return arr_agg, date_labels

        elif fz == 'Annual':
            # Compute fiscal/hydrological year for each date
            cal_years = dates.astype('datetime64[Y]').astype(int) + 1970
            cal_months = dates.astype('datetime64[M]').astype(int) % 12 + 1

            if year_end_month < 12:
                # Dates after year_end_month belong to next fiscal year
                fiscal_years = np.where(
                    cal_months <= year_end_month, cal_years, cal_years + 1
                )
            else:
                fiscal_years = cal_years

            unique_fiscal = np.unique(fiscal_years)

            aggregated_data = []
            for fy in unique_fiscal:
                mask = fiscal_years == fy
                aggregated_data.append(agg_func(arr[mask, :], axis=0))

            arr_agg = np.array(aggregated_data)
            date_labels = unique_fiscal.astype(str)

            if plurianual_agg:
                arr_agg = np.nanmean(arr_agg, axis=0, keepdims=True)
                date_labels = np.array(["Mean"])

        elif fz == 'Monthly':
            year_month = dates.astype('datetime64[M]')
            unique_months = np.unique(year_month)

            aggregated_data = []
            for ym in unique_months:
                mask = year_month == ym
                aggregated_data.append(agg_func(arr[mask, :], axis=0))

            arr_agg = np.array(aggregated_data)

            date_labels = np.array([
                f"{int(str(m).split('-')[1]):02d}-{str(m).split('-')[0]}"
                for m in unique_months.astype(str)
            ])

            if plurianual_agg:
                months_of_year = np.array([
                    int(str(m).split('-')[1]) for m in unique_months.astype(str)
                ])
                unique_month_nums = np.unique(months_of_year)

                plurianual_data = []
                for month_num in unique_month_nums:
                    mask = months_of_year == month_num
                    plurianual_data.append(np.nanmean(arr_agg[mask, :], axis=0))

                arr_agg = np.array(plurianual_data)
                date_labels = np.array([f"{m:02d}" for m in unique_month_nums])

        else:
            raise ValueError(f"Unknown frequency: {fz}. Use 'Annual', 'Monthly', or 'Daily'.")

        print(f"Aggregated shape: {arr_agg.shape}", flush=True)
        print("Done", flush=True)

        return arr_agg, date_labels

    @staticmethod
    def convert_watbal_units(
        data: np.ndarray,
        cell_areas: np.ndarray,
        target_unit: str,
    ) -> np.ndarray:
        """
        Vectorized conversion of water balance data from CaWaQS m3/s convention.

        :param data: Array (n_cells, n_timesteps) of values in m3/s
        :type data: np.ndarray
        :param cell_areas: 1D array (n_cells,) of cell areas in m2
        :type cell_areas: np.ndarray
        :param target_unit: Target unit ('mm/j', 'm3/j', 'l/s')
        :type target_unit: str
        :return: Converted array, same shape as data
        :rtype: np.ndarray
        """
        if target_unit == 'mm/j':
            # m3/s -> mm/day: multiply by 86400 (s/day) * 1e3 (mm/m) / area (m2)
            return data * (86400.0 * 1e3 / cell_areas[:, np.newaxis])
        elif target_unit == 'm3/j':
            return data * 86400.0
        elif target_unit == 'l/s':
            return data * 1e3
        elif target_unit == 'm3/s':
            return data
        else:
            raise ValueError(
                f"Unknown target unit: '{target_unit}'. "
                f"Use 'mm/j', 'm3/j', 'l/s', or 'm3/s'."
            )

    @staticmethod
    def compute_effective_rainfall(
        rain: np.ndarray,
        etr: np.ndarray,
    ) -> np.ndarray:
        """Compute effective rainfall: Pe = max(rain - etr, 0).

        :param rain: (n_cells, n_timesteps) rainfall in target units
        :param etr: (n_cells, n_timesteps) evapotranspiration in same units
        :return: (n_cells, n_timesteps) effective rainfall, clipped to >= 0
        """
        pe = rain - etr
        pe[pe < 0] = 0
        return pe

    def sp_operator(
        self,
        data: np.ndarray,
        operation: str,
        areas: np.ndarray = None,
        compartment: Compartment = None
    ) -> np.ndarray:
        """
        Perform spatial averaging operations on simulation data.
        
        :param data: Array (n_cells, n_timesteps) of simulated values
        :type data: np.ndarray
        :param operation: Type of spatial average ('arithmetic', 'weighted',
            'geometric', 'harmonic')
        :type operation: str
        :param areas: 1D array (n_cells,) of cell areas for weighted average. 
                    If None, extracted from compartment.
        :type areas: np.ndarray, optional
        :param compartment: Compartment object to extract areas from if not provided
        :type compartment: Compartment, optional
        :return: 1D array (n_timesteps,) averaged over space
        :rtype: np.ndarray
        """
        
        # Extract areas if not provided
        if areas is None:
            if compartment is None:
                raise ValueError("Either 'areas' or 'compartment' must be provided")
            
            areas = []
            for layer in compartment.mesh.mesh.values():
                for cell in layer.layer:
                    areas.append(cell.area)
            areas = np.array(areas)
        
        # Validate dimensions: rows = cells
        n_cells = data.shape[0]
        if len(areas) != n_cells:
            raise ValueError(
                f"Areas length ({len(areas)}) does not match number of cells ({n_cells})"
            )
        
        # Perform spatial averaging along axis=0 (cells)
        if operation == 'arithmetic':
            # Simple mean across cells
            return np.mean(data, axis=0)
        
        elif operation == 'weighted':
            # Area-weighted mean
            total_area = np.sum(areas)
            weights = areas[:, np.newaxis]  # Shape (n_cells, 1) for broadcasting
            return np.sum(data * weights, axis=0) / total_area
        
        elif operation == 'geometric':
            # Geometric mean: (∏ xi)^(1/n)
            # Handle potential zeros/negatives with small epsilon
            return np.exp(np.mean(np.log(np.abs(data) + 1e-10), axis=0))
        
        elif operation == 'harmonic':
            # Harmonic mean: n / (∑ 1/xi)
            # Handle potential zeros with small epsilon
            return n_cells / np.sum(1.0 / (data + 1e-10), axis=0)
        
        else:
            raise ValueError(
                f"Unknown operation: '{operation}'. "
                f"Choose from: 'arithmetic', 'weighted', 'geometric', 'harmonic'"
            )


class Extractor:
    def __init__(self):
        pass

    def extract_spatial(
        self,
        data: np.ndarray,
        cell_ids: Optional[List[int]] = None,
        compartment: Optional[Compartment] = None,
        spatial_operator: Optional[str] = None,
        spatial_manager = None,
        **operator_kwargs
    ) -> np.ndarray:
        """
        Extract data for specific cells based on their IDs or spatial operator.

        Two modes of operation:
        1. Direct extraction: provide cell_ids explicitly
        2. Operator-based: provide spatial_operator name (translates to cell_ids internally)

        :param data: Array (n_cells, n_timesteps) of simulated values
        :type data: np.ndarray
        :param cell_ids: List of cell IDs to extract. Use for manual selection.
        :type cell_ids: Optional[List[int]]
        :param compartment: Compartment object (required for spatial operators)
        :type compartment: Optional[Compartment]
        :param spatial_operator: Name of spatial operator ('catchment_cells' or
            'aquifer_outcropping')
        :type spatial_operator: Optional[str]
        :param spatial_manager: Instance of Manage.Spatial() (required for spatial operators)
        :param operator_kwargs: Additional kwargs for the spatial operator
        :return: Array (n_selected_cells, n_timesteps)
        :rtype: np.ndarray

        Available spatial operators:
        - 'catchment_cells': Upstream catchment cells from observation point
          Required kwargs: obs_point, network_gis_layer, network_col_name_cell,
                          network_col_name_fnode, network_col_name_tnode
        - 'aquifer_outcropping': Aquifer outcropping cells
          Required kwargs: exd, save (optional, default True)

        Examples:
            >>> # Manual cell selection
            >>> extractor.extract_spatial(data, cell_ids=[103, 245, 567])

            >>> # Catchment-based extraction
            >>> extractor.extract_spatial(
            ...     data,
            ...     spatial_operator='catchment_cells',
            ...     compartment=comp,
            ...     spatial_manager=spatial,
            ...     obs_point=pt,
            ...     network_gis_layer=layer,
            ...     ...
            ... )
        """

        # If spatial operator provided, translate to cell_ids
        if spatial_operator is not None:
            cell_ids = self._get_cell_ids_from_operator(
                operator=spatial_operator,
                compartment=compartment,
                spatial_manager=spatial_manager,
                **operator_kwargs
            )

        if cell_ids is None:
            raise ValueError("Either 'cell_ids' or 'spatial_operator' must be provided")

        # Extract data for the specified cells
        return data[cell_ids, :]

    def _get_cell_ids_from_operator(
        self,
        operator: str,
        compartment: Compartment,
        spatial_manager,
        **kwargs
    ) -> List[int]:
        """
        Translate spatial operator name into list of cell IDs.

        This method acts as a translator between operator names and the actual
        spatial analysis functions that identify relevant cells.

        :param operator: Spatial operator name
        :type operator: str
        :param compartment: Compartment object with mesh and configuration
        :type compartment: Compartment
        :param spatial_manager: Instance of Manage.Spatial()
        :param kwargs: Operator-specific parameters. ``**kwargs`` collects all
            additional keyword arguments into a dictionary called kwargs. This
            allows the function to accept a variable number of named parameters
            without listing them all explicitly.
        :return: List of cell IDs identified by the operator
        :rtype: List[int]

        Supported operators:
        - 'catchment_cells': Returns cell IDs for catchment upstream of observation point
        - 'aquifer_outcropping': Returns cell IDs where aquifer outcrops at surface
        """
        if spatial_manager is None:
            raise ValueError("spatial_manager is required for spatial operators")

        if compartment is None:
            raise ValueError("compartment is required for spatial operators")

        if operator == "catchment_cells":
            # Get catchment cells upstream of observation point
            return spatial_manager.getCatchmentCellsIds(
                obs_point=kwargs['obs_point'],
                network_gis_layer=kwargs['network_gis_layer'],
                network_col_name_cell=kwargs['network_col_name_cell'],
                network_col_name_fnode=kwargs['network_col_name_fnode'],
                network_col_name_tnode=kwargs['network_col_name_tnode']
            )

        elif operator == "aquifer_outcropping":
            # Get aquifer outcropping cells (returns Cell objects)
            outcrop_cells = spatial_manager.buildAqOutcropping(
                exd=kwargs['exd'],
                aq_compartment=compartment,
                save=kwargs.get('save', True)
            )
            # Extract cell IDs from Cell objects
            return [cell.id_abs for cell in outcrop_cells]

        else:
            raise NotImplementedError(
                f"Spatial operator '{operator}' not supported. "
                f"Available: 'catchment_cells', 'aquifer_outcropping'"
            )
    
    def extract_temporal(
        self,
        data: np.ndarray,
        dates: np.ndarray,
        start_date: Union[str, np.datetime64],
        end_date: Union[str, np.datetime64]
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Extract data for a specific time period based on date range.
        
        :param data: Array (n_cells, n_timesteps) of simulated values
        :type data: np.ndarray
        :param dates: Array of datetime64 objects corresponding to columns in data
        :type dates: np.ndarray
        :param start_date: Start date (format: 'YYYY-MM-DD' or datetime64)
        :type start_date: Union[str, np.datetime64]
        :param end_date: End date (format: 'YYYY-MM-DD' or datetime64)
        :type end_date: Union[str, np.datetime64]
        :return: Tuple of (extracted_data, extracted_dates)
        :rtype: Tuple[np.ndarray, np.ndarray]
        
        Example:
            >>> # Extract only data from 2020-2022
            >>> data_subset, dates_subset = extractor.extract_temporal(
            ...     data, dates, '2020-01-01', '2022-12-31'
            ... )
        """
        # Convert string dates to numpy datetime64 if needed
        if isinstance(start_date, str):
            start_date = np.datetime64(start_date)
        if isinstance(end_date, str):
            end_date = np.datetime64(end_date)
        
        # Create boolean mask for the date range
        mask = (dates >= start_date) & (dates <= end_date)
        
        # Extract data and dates
        extracted_data = data[:, mask]
        extracted_dates = dates[mask]
        
        print(f"Extracted {extracted_data.shape[1]} timesteps from {start_date} to {end_date}")
        
        return extracted_data, extracted_dates

class Comparator:
    def __init__(self):
        pass

    def calc_performance_metrics(
        self,
        sim: np.ndarray,
        obs: np.ndarray,
        metrics: List[str] = None
    ) -> dict:
        """
        Calculate performance metrics between simulated and observed data.

        :param sim: Simulated values (n_timesteps,)
        :type sim: np.ndarray
        :param obs: Observed values (n_timesteps,), may contain NaN
        :type obs: np.ndarray
        :param metrics: List of metrics to calculate. If None, calculates all.
        :type metrics: List[str], optional
        :return: Dictionary of metric_name: value
        :rtype: dict

        Available metrics:
        - 'nash': Nash-Sutcliffe Efficiency (NSE)
        - 'kge': Kling-Gupta Efficiency
        - 'rmse': Root Mean Square Error
        - 'pbias': Percent Bias
        - 'mae': Mean Absolute Error
        - 'r2': Coefficient of Determination
        - 'n_obs': Count of valid sim/obs pairs (after NaN removal)
        - 'avg_obs': Mean of observed values
        - 'avg_sim': Mean of simulated values
        - 'std_obs': Standard deviation of observed values
        - 'std_sim': Standard deviation of simulated values
        - 'std_ratio': Ratio of standard deviations (σ_sim / σ_obs)
        - 'avg_ratio': Ratio of averages (mean_sim / mean_obs)
        - 'sum_ratio': Ratio of sums (Σsim / Σobs)
        """
        if metrics is None:
            metrics = ["nash", "kge", "rmse", "pbias"]

        # Remove NaN values
        mask = ~np.isnan(obs)
        obs_clean = obs[mask]
        sim_clean = sim[mask]

        if len(obs_clean) == 0:
            return {metric: np.nan for metric in metrics}

        results = {}

        if "nash" in metrics:
            # Nash-Sutcliffe Efficiency
            mean_obs = np.mean(obs_clean)
            numerator = np.sum((obs_clean - sim_clean)**2)
            denominator = np.sum((obs_clean - mean_obs)**2)
            nse = 1 - (numerator / denominator) if denominator > 0 else np.nan
            results["nash"] = nse

        if "kge" in metrics:
            # Kling-Gupta Efficiency
            if len(obs_clean) > 1:
                r = np.corrcoef(sim_clean, obs_clean)[0, 1]
                alpha = np.std(sim_clean) / np.std(obs_clean) if np.std(obs_clean) > 0 else np.nan
                beta = np.mean(sim_clean) / np.mean(obs_clean) if np.mean(obs_clean) > 0 else np.nan
                kge = 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)
                results["kge"] = kge
            else:
                results["kge"] = np.nan

        if "rmse" in metrics:
            # Root Mean Square Error
            rmse = np.sqrt(np.mean((obs_clean - sim_clean)**2))
            results["rmse"] = rmse

        if "pbias" in metrics:
            # Percent Bias
            pbias = (
                100 * np.sum(sim_clean - obs_clean) / np.sum(obs_clean)
                if np.sum(obs_clean) != 0
                else np.nan
            )
            results["pbias"] = pbias

        if "mae" in metrics:
            # Mean Absolute Error
            mae = np.mean(np.abs(obs_clean - sim_clean))
            results["mae"] = mae

        if "r2" in metrics:
            # Coefficient of Determination
            if len(obs_clean) > 1:
                corr_matrix = np.corrcoef(sim_clean, obs_clean)
                r2 = corr_matrix[0, 1]**2
                results["r2"] = r2
            else:
                results["r2"] = np.nan

        if "n_obs" in metrics:
            results["n_obs"] = len(obs_clean)

        if "avg_obs" in metrics:
            results["avg_obs"] = np.mean(obs_clean)

        if "avg_sim" in metrics:
            results["avg_sim"] = np.mean(sim_clean)

        if "std_obs" in metrics:
            results["std_obs"] = np.std(obs_clean)

        if "std_sim" in metrics:
            results["std_sim"] = np.std(sim_clean)

        if "std_ratio" in metrics:
            std_o = np.std(obs_clean)
            results["std_ratio"] = np.std(sim_clean) / std_o if std_o > 0 else np.nan

        if "avg_ratio" in metrics:
            mean_o = np.mean(obs_clean)
            results["avg_ratio"] = np.mean(sim_clean) / mean_o if mean_o != 0 else np.nan

        if "sum_ratio" in metrics:
            sum_o = np.sum(obs_clean)
            results["sum_ratio"] = np.sum(sim_clean) / sum_o if sum_o != 0 else np.nan

        return results





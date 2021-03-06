# -*- coding: utf-8 -*-
from __future__ import division, print_function, absolute_import
from datetime import datetime
from itertools import product
import logging
import os
import os.path
from functools import partial

from IPython import parallel as ipyparallel
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from six.moves import zip

from ..utils import make_same_length, setdbspl, int2srt
import six


log = logging.getLogger(__name__)


class Experiment(object):
    """
    Performs a speech intelligibility experiment.


    The masker is truncated to the length of the target, or is padded with
    zeros if it is shorter than the target.

    Parameters
    ----------
    models : single model, or list
        List of intelligibility models.
    materials : object
        object that implements a `next` interface that returns the next
        pair of target and maskers.
    snrs : array_like
        List of SNRs.
    name : str,
        name of experiment, will be appended to the date when writing to file.
    write : bool, optional
        Write the result to file, as CSV, the default is True.
    output_path : string, optional.
        Path where the results will be written if `write` is True. The
        default is './output'.
    timestamp_format : str, optional
        Datetime timestamp format for the CSV file name. The default is of
        the form YYYYMMDD-HHMMSS.

    """

    def __init__(
            self,
            models,
            material,
            snrs,
            distortion=None,
            dist_params=(None,),
            fixed_level=65,
            fixed_target=True,
            name=None,
            write=True,
            output_path='./output/',
            timestamp_format="%Y%m%d-%H%M%S",
            adjust_levels_bef_proc=False
    ):
        self.models = models
        self.material = material
        self.snrs = snrs
        self.distortion = distortion
        self.dist_params = dist_params
        self.fixed_level = fixed_level
        self.fixed_target = fixed_target
        self.name = name
        self.timestamp_format = timestamp_format
        self.write = write
        self.output_path = output_path
        self.adjust_levels_bef_proc = adjust_levels_bef_proc
        self._key_full_pred = 'Full Prediction'
        self._key_value = 'Value'
        self._key_output = 'Output'
        self._key_dist_params = "Distortion params"
        self._key_models = 'Model'
        self._key_snr = 'SNR'
        self._key_material = 'Material'
        self._key_sent = 'Sentence number'
        self._all_keys = [
            self._key_full_pred,
            self._key_value,
            self._key_dist_params,
            self._key_models,
            self._key_snr,
            self._key_sent,
            self._key_material
        ]


    def preprocessing(self, target, masker, snr, params):
        """
        Applies preprocessing to the target and masker before setting the
        levels. In this case, the masker is padded with zeros if it is longer
        than the target, or it is truncated to be the same length as the target.

        :param target:
        :param masker:
        :return:
        """

        # Make target and masker same length
        if target.shape[-1] != masker.shape[-1]:
            target, masker = make_same_length(target, masker,
                                              extend_first=False)

        if self.adjust_levels_bef_proc:
            target, masker = self.adjust_levels(target, masker, snr)

        if params:
            if isinstance(params, dict):
                target, masker = self.distortion(target, masker, **params)
            else:
                target, masker = self.distortion(target, masker, *params)

        if not self.adjust_levels_bef_proc:
            target, masker = self.adjust_levels(target, masker, snr)
        return target, target + masker, masker

    def adjust_levels(self, target, masker, snr):
        """
        Adjusts level of target and maskers.

        Uses the `self.fixed_level` as the reference level for the target and
        masker. If `self.fixed_target` is True, the masker level is varied to
        set the required SNR, otherwise the target level is changed.

        :param target: ndarray
            Target signal.
        :param masker: ndarray
            Masker signal.
        :param snr: float
            SNR at which to set the target and masker.
        :return: tuple
            Level adjusted `target` and `masker`.
        """

        target_level = self.fixed_level
        masker_level = self.fixed_level
        if self.fixed_target:
            masker_level -= snr
        else:
            target_level += snr
        target = setdbspl(target, target_level)
        masker = setdbspl(masker, masker_level)
        return target, masker

    def next_masker(self, target, params):
        return self.material.ssn(target)

    def append_results(
            self,
            df,
            res,
            model,
            snr,
            i_target,
            params,
            **kwargs
    ):
        """
        Appends results to a DataFrame

        Parameters
        ----------
        df : dataframe
            DataFrame where the new results will be appended.
        res : dict
            Output dictionary from an intelligibility model.
        model: object
            Intelligibility model. Will use it's `name` attribute,
            if available, to add the source model to the DataFrame. Otherwise,
            the `__class__.__name__` attribute will be used.
        snr : float
            SNR at which the simulation was performed.
        i_target : int
            Number of the target sentence
        params : object
            Parameters that were passed to the distortion process.

        Returns
        -------
        df : dataframe
            DataFrame with new entry appended.
        """
        try:
            model_name = model.name
        except AttributeError:
            model_name = model.__class__.__name__
        try:
            material_name = self.material.name
        except AttributeError:
            material_name = self.material.__class__.__name__
        d = {
            self._key_snr: snr
            , self._key_models: model_name
            , self._key_sent: i_target
            , self._key_full_pred: res
            , self._key_material: material_name
        }
        # If the distortion parameters are in a dictionary, put each value in
        # a different column. Otherwise, group everything in a single column.
        if isinstance(params, dict):
            for k, v in six.iteritems(params):
                d[k] = v
        else:
            # Make sure the values are hashable for later manipulation
            if isinstance(params, list):
                params = tuple(params)
            else:
                pass
            d[self._key_dist_params] = params

        for name, value in six.iteritems(res['p']):
            d[self._key_output] = name
            d[self._key_value] = value
            df = df.append(d, ignore_index=True)

        return df

    def _model_prediction(self, model, target, mix, masker):
        """Call the `predict` method of an intelligibility model.

        Parameters
        ----------
        model :
            Speech intelligibility model
        target, mix, masker : ndarray
            Input signals for the model prediction

        Returns
        -------
        res : dict
            Model prediction.

        Notes
        -----
        The sole purpose of this function is to make it easier to override if
        the model used does not have a `predict` method, but maybe a
        `predict_snr` method or the like.
        """
        return model.predict(target, mix, masker)

    def _predict(self, ii_and_target, snr, model, params):
        i_target, target = ii_and_target
        masker = self.next_masker(target, params)

        target, mix, masker = self.preprocessing(
            target,
            masker,
            snr,
            params
        )
        res = self._model_prediction(model, target, mix, masker)

        # Initialize the dataframe in which the results are saved.
        df = pd.DataFrame()
        df = self.append_results(
            df,
            res,
            model,
            snr,
            i_target,
            params
        )
        return df

    def _parallel_run(self, n=None, seed=0, profile=None):
        """ Run the experiment using IPython.parallel

        Parameters
        ----------
        n : int
            Number of sentences to process.
        seed : int
            Seed for the random number generator. Default is 0.

        Returns
        -------
        df : pd.Dataframe
            Pandas dataframe with the experimental results.

        """
        if profile:
            rc = ipyparallel.Client(profile=profile)
        else:
            rc = ipyparallel.Client()
        all_engines = rc[:]
        all_engines.use_dill()
        with all_engines.sync_imports():
            import os
        all_engines.apply(os.chdir, os.getcwd())

        lview = rc.load_balanced_view()
        lview.block = True
        lview.apply(np.random.seed, seed)

        try:
            iter(self.models)
        except TypeError:
            self.models = [self.models]

        # Initialize the dataframe in which the results are saved.
        df = pd.DataFrame()

        targets = self.material.load_files(n)
        conditions = product(
            enumerate(targets),
            self.snrs,
            self.models,
            self.dist_params
        )
        lview_res = all_engines.map(self._predict, *zip(*conditions))

        for each in lview_res:
            df = df.append(each, ignore_index=True)

        return df

    def _single_run(self, n, seed):
        """ Run the experiment locally using a for-loop.

        Parameters
        ----------
        n : int
            Number of sentences to process.
        seed : int
            Seed for the random number generator. Default is 0.

        Returns
        -------
            Pandas dataframe with the experimental results.
        """

        np.random.seed(seed)

        targets = self.material.load_files(n)
        # Initialize the dataframe in which the results are saved.
        df = pd.DataFrame()
        for ii, ((i_target, target), params, snr, model) \
                in enumerate(product(
                enumerate(targets),
                self.dist_params,
                self.snrs,
                self.models
        )):
            log.debug("Running with parameters {}".format(params))
            masker = self.next_masker(target, params)

            target, mix, masker = self.preprocessing(
                target,
                masker,
                snr,
                params
            )
            log.info("Simulation # %s\t SNR: %s, sentence %s", ii, snr,
                     i_target)
            res = self.prediction(model, target, mix, masker)

            df = self.append_results(
                df,
                res,
                model,
                snr,
                i_target,
                params
            )
        return df

    def run(self, n=None, seed=0, parallel=False, profile=None,
            output_filename=None):
        """ Run the experiment.

        Parameters
        ----------
        n : int
            Number of sentences to process.
        seed : int
            Seed for the random number generator. Default is 0.
        parallel : bool
            If False, the experiment is ran locally, using a for-loop. If
            True, we use IPython.parallel to run the experiment in parallel.
            We try to connect to the current profile.
        output_filename : string
            Name of the output file where the results will be saved. If it is
            `None`, the default is to use the current date and time. The
            default is `None`.

        Returns
        -------
        df : pd.Dataframe
            Pandas dataframe with the experimental results.

        """
        try:
            iter(self.models)
        except TypeError:
            self.models = (self.models,)

        if parallel:
            df = self._parallel_run(n, seed, profile=profile)
        else:
            df = self._single_run(n, seed)

        if self.write:
            self._write_results(df, filename=output_filename)
        return df

    def _write_results(self, df, filename=None):
        """Writes results to CSV file.

        Will drop the column where all the complete model output is stored
        before writing to disk.

        Parameters
        ----------
        df : dataframe

        Returns
        -------
        filepath : str
            Path to the CSV file.

        Raises
        ------
        IOError : Raise if the path where to write the CSV file is not
        accessible. Additionally, the function tries to save the CSV file to
        the current directory, in order not to loose the simulation data.

        """
        if filename is None:
            timestamp = datetime.now()
            date = timestamp.strftime(self.timestamp_format)
            if self.name:
                name = "-{}".format(self.name)
            else:
                name = ''
            filename = "{date}{name}.csv".format(date=date, name=name)

        if not os.path.isdir(self.output_path):
            try:
                os.mkdir(self.output_path)
                log.info('Created directory %s', self.output_path)
            except IOError as e:
                log.error("Could not create directory %s", self.output_path)
                log.error(e)

        output_file = os.path.join(self.output_path, filename)
        try:
            df.drop(self._key_full_pred, axis=1).to_csv(output_file)
            log.info('Saved CSV file to location: {}'.format(output_file))
        except IOError as e:
            try:
                alternate_path = os.path.join(os.getcwd(), filename)
                err_msg = 'Could not write CSV file to path: {}, tried to ' \
                          'save to ' \
                          '{} in order not to loose data.'.format(
                    output_file, alternate_path)
                log.error(err_msg)
                raise
            finally:
                try:
                    df.drop(self._key_full_pred, axis=1).to_csv(alternate_path)
                except:
                    pass
        else:
            return output_file

    @staticmethod
    def prediction(model, target, mix, masker):
        """
        Predicts intelligibility for a target and masker pair. The target and
        masker are simply added together to create the mixture.

        Parameters
        ----------
        model :
        target :
        masker :

        Returns
        -------
        :return:
        """
        return model.predict(target, mix, masker)

    def _get_groups(self, df, var=None):
        """Get of variables for plotting.

        Ignored variables should be:
        - SNR
        - Sentence number

        :param df:
        :param var:
        :return:
        """

        # Use the single "Distortion params" column if available and not
        # None. Else, consider all "extra columns" as parameters.
        if self._key_dist_params in df.columns:
            # Use the distortion parameters only if it's not None.
            if df[self._key_dist_params].unique().any():
                params = [self._key_dist_params]
            else:
                params = []
        else:
            params = list(set(df.columns) - set(self._all_keys)
                          - {'Intelligibility'})
        # If var is defined, remove it from the groups
        if var:
            params = list(set(params) - set([var]))
        log.debug("Found the following parameter keys %s.", params)
        if len(np.unique(df[params])):
            groups = params + [self._key_snr, self._key_models]
        else:
            groups = [self._key_snr, self._key_models]
        log.debug("The plotting groups are: %s.", groups)
        return groups

    def plot_results(self,
                     df,
                     var=None,
                     xlabel='SNR (dB)',
                     ylabel='% Intelligibility',
                     ax=None
    ):
        df = df.convert_objects()
        # Drop the column with the full prediction results
        if self._key_full_pred in df.columns:
            df = df.drop(self._key_full_pred, axis=1)

        groups = self._get_groups(df, var)

        grouped_cols = df.groupby(groups).mean().unstack(
            self._key_snr).T

        # If "Var" is not defined, use the "Intelligibility" column if it
        # exists. Otherwise, use the key defined in the model.
        if not var:
            if "Intelligibility" in df.columns:
                var = 'Intelligibility'
            else:
                var = self._key_value
        log.debug("Plotting the variable `%s`.", var)

        ax = grouped_cols.xs(var).plot(ax=ax)
        if var == 'Intelligibility':
            log.debug("Setting the limits to intelligibility.")
            plt.ylim((0, 100))

        plt.legend(loc='best')
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
        return ax

    def pred_to_pc(
            self,
            df,
            fc,
            col='Value',
            models=None,
            out_name='Intelligibility'
    ):
        """Converts the data in a given column to percent correct.

        Parameters
        ----------
        df : Dataframe
            Dataframe where the intelligibility predictions are stored.
        fc : function
            The function used to convert the model outputs to
            intelligibility. The function must take a float as input and
            returns a float.
        col : string
            Name of the column to convert to intelligibility. The default is
            "Value".
        models : string, list or dict
            This argument can either be a string, with the name of the model
            for which the output value will be transformed to
            intelligibility, or a list of model names. The argument can also
            be a dictionary where the keys are model names and the values are
            "output names", i.e. the name of the value output by the model.
            This is useful if a model has multiple prediction values. The
            default is `None`, all the rows will be converted with the same
            function.
        out_name : str
            Name of the output column (default: 'Intelligibility')

        Returns
        -------
        df : dataframe
            Dataframe with the new column column with intelligibility values.
        """
        try:
            df[out_name]
        except KeyError:
            df[out_name] = np.nan

        if models:
            if isinstance(models, list):
                for model in models:
                    df.loc[df[self._key_models] == model, out_name] \
                        = df.loc[df[self._key_models] == model, col].map(fc)
            elif isinstance(models, dict):
                for model, v in six.iteritems(models):
                    key = (df[self._key_models] == model) & (
                        df[self._key_output] == v)
                    df.loc[key, out_name] = df.loc[key, col].map(fc)
            else:
                df.loc[df[self._key_models] == models, out_name] = \
                    df.loc[df[self._key_models] == models, col].map(fc)
        else:
            df.loc[:, out_name] = df.loc[:, col].map(fc)
        return df

    def srts_from_df(self, df, col='Intelligibility', srt_at=50,
                     model_srts=None):
        """Get dataframe with SRTs

        Parameters
        ----------
        df : Data Frame
            DataFrame resulting from an experiment. It must have an
            "Intelligibility" column.
        col : string (optional)
            Name of the column to use for the SRT calculation. The default
            value is the 'Intelligibility' column.
        srt_at : float, tuple (optional)
            Value corresponding to the SRT. The default is 50 (%).
        model_srts : dict
            Overrides default ``srt_at`` for particular models. The dictionary
            must be a tuple of the model name and model output: ('Model',
            'Output')
        Returns
        -------
        out : Data frame
            Data frame, with an SRT column.
        """
        snrs = df['SNR'].unique()
        averaging_groups = self._get_groups(df)
        # Average across sentence
        mean_df = df.groupby(averaging_groups).mean().reset_index()

        # Join both columns as tuple
        mean_df['model_output_pair'] = list(zip(mean_df['Model'],
                                                mean_df['Output']))
        model_output_pairs = mean_df.model_output_pair.unique()

        # Set default criterion for all models
        transformations = {pair: partial(int2srt, snrs, srt_at=srt_at)
                           for pair in model_output_pairs}
        # Override for specified models
        if model_srts is not None:
            for (model, output), criterion in model_srts.iteritems():
                transformations[(model, output)] = partial(int2srt, snrs,
                                                           srt_at=criterion)

        # Replace Model and Output column with a single column for grouping.
        condition_groups = list(set(averaging_groups) - {'Model', 'Output'}
                                | {'model_output_pair'})
        agg_groups = list(set(condition_groups) - {'model_output_pair', 'SNR'})
        srts = mean_df.set_index(condition_groups) \
            .unstack('model_output_pair')[col].reset_index() \
            .groupby(agg_groups).agg(transformations)
        srts = pd.melt(srts.reset_index(),
                       id_vars=agg_groups,
                       var_name=['Model', 'Output'],
                       value_name='SRT'
        )
        srts.sort('Model', inplace=True)
        return srts

class AdaptiveExperiment(Experiment):
    """

    Attributes
    ----------

    Parameters
    ----------
    pred_keys_and_thresholds : list of tuples
        List of the model output and corresponding threshold for each model,
        of the form: ('output_name', threshold). e.g. [('snr_env', 33.5)].
    start_snr : float
        SNR at which to start the procedure. Default is 20 dB SNR.
    step_size : list of floats
        Step sizes. Multiple values can be used if the step size should
        change according to the number of reversals. The default value is
        (4, 2, 1) The reversal where the step size changes depends on
        `change_step_on`.
    n_test_reversals : int
        Number of reversals to consider when calculating the threshold. The
        default value is 6 reversals.
    change_step_on : int (-1 or 1)
        Change step size on downward reversal (-1) or upward reversal (1).
        Default value is -1.
    """
    def __init__(self,
                 pred_keys_and_thresholds,
                 start_snr=20,
                 step_sizes=(4., 2., 1.),
                 n_test_reversals=6,
                 change_step_on=-1,
                 **kwargs
    ):
        self.pred_keys_and_thresholds = pred_keys_and_thresholds
        self.start_snr = start_snr
        self.step_sizes = step_sizes
        self.n_test_reversals = n_test_reversals
        self.change_step_on = change_step_on
        super(AdaptiveExperiment, self).__init__(**kwargs)

    def run(self, n=None, seed=0, parallel=False):
        np.random.seed(seed)

        targets = self.material.load_files(n)
        # Initialize the dataframe in which the results are saved.
        df = pd.DataFrame()
        for ii, ((i_target, target), params, model_and_keys) \
                in enumerate(product(
                                     enumerate(targets),
                                     self.dist_params,
                                     zip(self.models,
                                         self.pred_keys_and_thresholds
                                     )
        )):
            log.debug("Running with parameters {}".format(params))
            masker = self.next_masker(target, params)

            model, (pred_key, threshold) = model_and_keys
            log.debug("Prediction key: {}, and threshold {}".format(
                pred_key, threshold))

            test_reversals = 0
            total_reversals = 0
            snr = self.start_snr
            last_reversal_sign = -1

            i_step = 0
            all_res = []
            while test_reversals <= self.n_test_reversals:

                target, mix, masker = self.preprocessing(
                    target,
                    masker,
                    snr,
                    params
                )
                log.info("Simulation # %s\t SNR: %s, sentence %s", ii, snr,
                         i_target)
                res = self.prediction(model, target, mix, masker)
                pred = res['p'][pred_key]

                all_res.append((snr, pred))
                if pred >= threshold:
                    snr -= self.step_sizes[i_step]
                    log.debug('Decreased SNR to {}, with step size {}'
                        .format(snr, self.step_sizes[i_step]))
                    if last_reversal_sign > 0:
                        last_reversal_sign = -1
                        log.debug("Changed reversal sign to %s", last_reversal_sign)
                        i_step = min(i_step + 1, len(self.step_sizes) - 1)
                        if i_step == len(self.step_sizes) - 1:
                            test_reversals += 1
                    else:
                        pass  # Keep going down
                else:  # prediction is below threshold
                    snr += self.step_sizes[i_step]
                    log.debug('Increased SNR to {}, with step size {}'
                        .format(snr, self.step_sizes[i_step]))
                    if last_reversal_sign < 0:
                        last_reversal_sign = 1
                        log.debug("Changed reversal sign to %s", last_reversal_sign)
                        if i_step == len(self.step_sizes) - 1:
                            test_reversals += 1
                    else:
                        pass  # Keep going up.
                total_reversals += 1

            srt = np.mean([each[0] for each in all_res[-self.n_test_reversals:]])

            df = self.append_results(
                df,
                res,
                model,
                snr,
                i_target,
                params,
                SRT=srt,
                Reversals=total_reversals
            )
        return df







def srt_dict_to_dataframe(d):
    df_srts = pd.DataFrame()
    for k, v in six.iteritems(d):
        model, material, tdist, mdist = k.split('_')

        try:
            srt = v[0]
        except TypeError:
            srt = np.nan

        df_srts = df_srts.append({'model': model,
                                  'tidst': tdist,
                                  'mdist': mdist,
                                  'srt': srt},
                                 ignore_index=True)
    df_srts = df_srts.convert_objects(convert_numeric=True, )
    return df_srts.sort(['model', 'mdist'])


def plot_srt_dataframe(df):
    for key, grp in df.groupby('model'):
        plt.plot(grp['mdist'], grp['srt'], label=key)
    plt.legend(loc='best')
    plt.xlabel('Masker distance')
    plt.ylabel('SRT (dB)')

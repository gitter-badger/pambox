from __future__ import division
import pytest
from scipy.io import wavfile
import numpy as np
import scipy.io as sio
from pambox.intelligibility_models import sepsm
from numpy.testing import assert_allclose


@pytest.fixture
def speech_raw():
    x = wavfile.read("test_files/test_speech_raw_22050.wav")[1]
    return x / 2. ** 15


@pytest.fixture
def noise_raw():
    x = wavfile.read("test_files/test_noise_raw_22050.wav")[1]
    return x / 2. ** 15


@pytest.fixture
def mix_0dB():
    x = wavfile.read("test_files/test_mix_0dB_22050.wav")[1]
    return x / 2. ** 15


@pytest.fixture
def noise_65dB():
    x_65 = wavfile.read("test_files/test_noise_65dB_22050.wav")[1]
    return x_65 / 2. ** 15


@pytest.fixture
def center_f():
    return np.array([63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800,
                     1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000,
                     6300, 8000])


@pytest.fixture
def mat_snr_env():
    return sio.loadmat('./test_files/test_snr_env.mat')


def test_select_bands_above_threshold(center_f):
    mat = sio.loadmat("./test_files/test_bands_above_threshold.mat")
    noise_rms = mat['mix_rms_out'].squeeze()
    target = mat['bands_to_process'][0]

    c = sepsm.Sepsm(cf=center_f)
    bands_above_thres = c._bands_above_thres(noise_rms)
    # Make 1-based to compare with matlab
    bands_above_thres += 1
    assert np.array_equal(bands_above_thres, target)


def test_snr_env(mat_snr_env):
    """@todo: Docstring for test_snr_env_for_simple_signals.
    :returns: @todo

    """
    clean = mat_snr_env['clean'].squeeze()
    noise = mat_snr_env['noise'].squeeze()
    mix = mat_snr_env['mix'].squeeze()
    fs_env = mat_snr_env['fsNew'].squeeze()
    target_snr_env = mat_snr_env['snr_env'].squeeze()
    target_excitation_patterns = mat_snr_env['env_excitation_patterns'].\
        squeeze().T
    modf = np.array([1., 2., 4., 8., 16., 32., 64.])

    signals = (clean, mix, noise)
    c = sepsm.Sepsm(modf=modf)
    snrenv, excitation_patterns = c._snr_env(signals, fs_env)
    assert_allclose(snrenv, target_snr_env)
    assert_allclose(excitation_patterns, target_excitation_patterns)

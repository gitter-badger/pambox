# -*- coding: utf-8 -*-
from __future__ import division
import numpy as np
import scipy as sp
from scipy.io import wavfile
from numpy import min, log2, ceil, argmin, zeros, arange, complex
try:
    np.use_fastnumpy
    from numpy.fft import fft, ifft
except AttributeError:
    from scipy.fftpack import fft, ifft


def dbspl(x, ac=False, offset=100.0, axis=-1):
    """RMS value of signal (in dB)

    DBSPL(x) computes the SPL (sound pressure level) of the input signal
    measured in dB, using the convention that a pure tone at 100 dB SPL has
    an RMS value of 1.

    DBSPL(x, ac=True) does the same, but considers only the AC component of the
    signal (i.e. the mean is removed).

    See also: setdbspl

    References:
      Auditory Modeling Toolbox, Peter L. Soendergaard
      B. C. J. Moore. An Introduction to the Psychology of Hearing. Academic
      Press, 5th edition, 2003.


    :x: arraly_like, signal ac: bool, consider only the AC component of the
    :signal. offset: float, reference to convert between RMS and dB SPL.
    """
    x = np.asarray(x)
    return 20. * np.log10(rms(x, ac=ac, axis=axis)) + float(offset)


def setdbspl(x, lvl, ac=False, offset=100.0):
    """Sets the level of signal in dB SPL.

    :x: array_like
        Signal.
    :lvl: float
        Level, in dB SPL at which to set the signal. The level is set in
        reference to
    :ac: bool, optional
        Calculate the AC RMS power of the signal by default (`ac=True`),
        e.g. the mean is removed. If  `False`, considers the non-RMS power.
    :offset: float, optional
        Level, in dB SPL, corresponding to an RMS of 1. By default, an RMS of
        1 corresponds to 100 dB SPL.
    """
    axis = -1
    x = np.asarray(x)
    return (x.T / rms(x, ac, axis=axis)
            * 10. ** ((lvl - float(offset)) / 20.)).T


def rms(x, ac=False, axis=-1):
    """RMS value of a signal.

    :x: signal
    :ac: bool, default: False
        Consider only the AC component of the signalG
    :axis: int
        Axis on which to calculate the RMS value. The default is to calculate
        the RMS on the last dimensions, i.e. axis = -1.
    :rms: rms value

    """
    x = np.asarray(x)
    if not x.ndim > 1:
        axis = -1
    if ac:
        return np.linalg.norm((x - np.mean(x, axis=axis))
                              / np.sqrt(x.shape[axis]), axis=axis)
    else:
        return np.linalg.norm(x / np.sqrt(x.shape[axis]), axis=axis)


def hilbert_envelope(signal):
    """Calculate the hilbert envelope of a signal

    :param signal: array_like, signal on which to calculate the hilbert
    envelope. The calculation is done on the last axis (i.e. ``axis=-1``).
    :returns: ndarray of the same shape as the input.
    """
    signal = np.asarray(signal)
    n_orig = signal.shape[-1]
    # Next power of 2.
    N = next_pow_2(n_orig)
    y_h = sp.signal.hilbert(signal, N)
    # Return signal with same dimensions as original
    return np.abs(y_h[..., :n_orig])


def next_pow_2(x):
    """Calculate the next power of 2."""
    return int(pow(2, np.ceil(np.log2(x))))


def fftfilt(b, x, *n):
    """Filter the signal x with the FIR filter described by the
    coefficients in b using the overlap-add method. If the FFT
    length n is not specified, it and the overlap-add block length
    are selected so as to minimize the computational cost of
    the filtering operation.

    From: http://projects.scipy.org/scipy/attachment/ticket/837/fftfilt.py
    """
    x = np.asarray(x)
    b = np.asarray(b)

    if b.ndim > 1 or x.ndim > 1:
        raise ValueError('The inputs should be one dimensional')

    N_x = len(x)
    N_b = len(b)

    # Determine the FFT length to use:
    if len(n):
        # Use the specified FFT length (rounded up to the nearest
        # power of 2), provided that it is no less than the filter
        # length:
        n = n[0]
        if n != int(n) or n <= 0:
            raise ValueError('n must be a nonnegative integer')
        if n < N_b:
            n = N_b
        N_fft = 2 ** next_pow_2(n)
    else:
        if N_x > N_b:
            # When the filter length is smaller than the signal,
            # choose the FFT length and block size that minimize the
            # FLOPS cost. Since the cost for a length-N FFT is
            # (N/2)*log2(N) and the filtering operation of each block
            # involves 2 FFT operations and N multiplications, the
            # cost of the overlap-add method for 1 length-N block is
            # N*(1+log2(N)). For the sake of efficiency, only FFT
            # lengths that are powers of 2 are considered:
            N = 2 ** arange(ceil(log2(N_b)), 27)
            cost = ceil(N_x / (N - N_b + 1)) * N * (log2(N) + 1)
            N_fft = N[argmin(cost)]
        else:
            # When the filter length is at least as long as the signal,
            # filter the signal using a single block:
            N_fft = next_pow_2(N_b + N_x - 1)

    N_fft = int(N_fft)

    # Compute the block length:
    L = int(N_fft - N_b + 1)

    # Compute the transform of the filter:
    H = fft(b, N_fft)

    y = zeros(N_x, complex)
    i = 0
    while i <= N_x:
        il = min([i + L, N_x])
        k = min([i + N_fft, N_x])
        yt = ifft(fft(x[i:il], N_fft) * H, N_fft)  # Overlap..
        y[i:k] = y[i:k] + yt[:k - i]  # and add
        i += L
    return np.real(y)


def write_wav(fname, fs, x):
    """Write floating point numpy array to 16 bit wavfile.

    Convenience wrapper around the scipy.io.wavfile.write function. The signal
    so that its maximum value is one.

    The '.wav' extension is added to the file if it is not part of the
    filename string.

    :fname: string, filename with path.
    :fs: sampling frequency
    :x: array_like, N_channel x Length, signal
    :return: nothing
    """
    # Make sure that the channels are the second dimension
    fs = np.int(fs)
    if not fname.endswith('.wav'):
        fname += '.wav'

    if x.shape[0] <= 2:
        x = x.T

    if x is np.float:
        scaled = (x / np.max(np.abs(x)) * (2 ** 15 - 1))
    else:
        scaled = x
    wavfile.write(fname, fs, scaled.astype('int16'))

def make_same_length(a, b, extend_first=True):
    """Makes two arrays the same length.

    Default behavior is to zero-pad the shorted array. It is also possible to
    cut the second array to the same length as the first.

    :param a: 1d array, first vector.
    :param b: 1d array, second vector.
    :param extend_first: bool, optional. Zero-pad the first array if it is the
    shortest if `True`. Otherwise, cut array `b` to the length of `a`.

    :return: tuple of ndarray, both vectors with same length.
    """
    if len(a) < len(b):
        if extend_first:
            c = np.zeros_like(b)
            c[:len(a)] += a
            return c, b
        else:
            return a, b[:len(a)]
    else:
        c = np.zeros_like(a)
        c[:len(b)] += b
        return a, c


def add_signals(a, b):
    """Add two vectors of different lengths by zero padding the shortest one.

    :a: vector
    :b: vector
    :return: vector, of the same length as the longest of the two inputs.
    """
    if len(a) < len(b):
        c = b.copy()
        c[:len(a)] += a
    else:
        c = a.copy()
        c[:len(b)] += b
    return c


def int2srt(x, y, srt=50.0):
    """Find intersection using linear interpolation.

    This function finds the x values at which a curve intersects with a
    constant value.

    :x: x values
    :y: y values
    :srt: value of `y` at which the interception is calculated.

    Raises
    ------
    ValueError: inputs of different lenghts.

    """
    x = np.asarray(x)
    y = np.asarray(y)

    if x.shape != y.shape:
        raise ValueError('Inputs of different lenghts.')
    srt = np.float(srt)
    idx = np.nonzero(np.diff(y >= srt))[0]
    if not idx and y[0] == srt:
        return x[0]

    if len(idx) >= 1:
        srt = x[idx] + (srt - y[idx]) * (x[idx + 1] - x[idx]) \
            / (y[idx + 1] - y[idx])
    else:
        srt = None
    return srt


def add_signals(a, b):
    """Add two vectors of different lengths by zero padding the shortest one.

    :a: 1d array, first vector.
    :b: 1d array, second vector.

    :return: ndarray, sum of both vectors.
    """
    if len(a) < len(b):
        c = b.copy()
        c[:len(a)] += a
    else:
        c = a.copy()
        c[:len(b)] += b
    return c

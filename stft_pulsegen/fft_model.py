# SingularitySurfer 2020

import numpy as np
import matplotlib.pyplot as plt


class FftModel:
    """fixed point radix2 dit fft with fixed point scaling numerical model

    Takes a complex fixed point vector with fixed point position to take the fft of.
    The data is stored in an internal vector and successive fft stages can be performed.

    Fixed point is modeled via integers and bitshifting.
    Unfortunately this means some more interpretation of intermediate results...
    Overflows are captured by the model, if the total nr of bits for real/complex data is provided.
    Sign bit is not included.


    Parameters
        ----------
    x_in : complex array
        complex input vector
    w_p : int
        twiddle factor (fractional) bits.
    x_bits: int
        total number of bits in input, used for overflow checking
    """

    def __init__(self, x_in, w_p=16, x_bits=1024):
        self.x_bits = x_bits
        self.w_p = w_p
        self.size = len(x_in)  # Nr samples
        assert np.log2(self.size) % 1 == 0, 'input length has to be power of two!'
        self.stages = int(np.log2(self.size))  # Nr stages (als nr. bits of index)
        self.stage = 0  # current stage
        self._bfls = int(self.size / 2)  # nr _bfls per stage
        x_brev = self.bit_reverse(x_in, self.stages)  # bit reverse
        self.xr = x_brev.real.astype(int)  # real fixedpoint mem
        self.xi = x_brev.imag.astype(int)  # imag fixedpoint mem
        w = np.exp(-2j * (np.pi / self.size) * np.arange(self.size / 2))  # only uses half circle twiddles
        self.wr = np.round((w.real * 2 ** self.w_p)).astype(int)  # real twiddle mem
        self.wi = np.round((w.imag * 2 ** self.w_p)).astype(int)  # imag twiddle mem

    def full_fft(self, scaling='one', ifft=False):
        """perform full fft and return output data"""
        for i in range(self.stages):
            if scaling == 'none':  # no scaling
                self.fft_stage(0, ifft)
            elif scaling == 'one':  # scale by one in each stage
                self.fft_stage(1, ifft)
            elif scaling == 'no_oflw':  # scale by one in first and second stage and by two in later
                if i < 2:  # no overflows in real arch guaranteed
                    self.fft_stage(1, ifft)
                else:
                    self.fft_stage(2, ifft)
            elif scaling == '4tone_ifft':  # scale on first two stages and then no more
                if i < 2:
                    self.fft_stage(1, ifft)
                else:
                    self.fft_stage(0, ifft)
            elif isinstance(scaling, int):
                self.fft_stage(int((1 << i) & scaling != 1 << i), ifft)

        return self.xr + 1j * self.xi

    def fft_stage(self, s, ifft=False):
        """perform radix2 stage with scaling on data"""
        assert (np.amax(abs(self.xr)) < 2 ** (self.x_bits + 1)), "OVERFLOW!"
        assert (np.amax(abs(self.xi)) < 2 ** (self.x_bits + 1)), "OVERFLOW!"
        t_s = self._bfls >> self.stage  # twiddle index step size
        for i in range(self._bfls):
            w_idx = (t_s * i) % self._bfls  # twiddle factor index for each stage. wraps around.
            q = (1 << self.stage) - 1  # lower bits bitmask ie 000000000011 for s=3. responsible for consecuteve parts
            x_idx = (((i & ~q) << 1) | (i & q)) + (1 << self.stage)  # compute memory adress.
            ar, ai = self.xr[x_idx - (1 << self.stage)], self.xi[x_idx - (1 << self.stage)]  # mem access
            br, bi = self.xr[x_idx], self.xi[x_idx]
            wr, wi = self.wr[w_idx], self.wi[w_idx]
            wi = -wi if ifft else wi  # complex conjugate for ifft
            cr, ci, dr, di = self._bfl_dsp_opt(ar, ai, br, bi, wr, wi, self.w_p, s)  # butterfly with no scaling
            self.xr[x_idx - (1 << self.stage)], self.xi[x_idx - (1 << self.stage)] = cr, ci
            self.xr[x_idx], self.xi[x_idx] = dr, di
        self.stage += 1
        assert (np.amax(abs(self.xr)) < 2 ** (self.x_bits + 1)), "OVERFLOW!"
        assert (np.amax(abs(self.xi)) < 2 ** (self.x_bits + 1)), "OVERFLOW!"

    def _bfl_dsp_opt(self, ar, ai, br, bi, wr, wi, p, s):
        """Butterfly computation pipe.
        Optimized for pipelined dsp blocks. Adapted from misoc ComplexMultiplier."""

        bias = (1 << p - 1) - 1

        bd = br + bi
        m0 = bd * wr
        m1 = m0 + bias
        ws = wr + wi
        wd = wr - wi
        m2 = ws * bi
        m3 = wd * br
        m6 = m1 - m2
        m7 = m1 - m3
        cr = (ar + (m6 >> p)) >> s
        ci = (ai + (m7 >> p)) >> s
        dr = (ar - (m6 >> p)) >> s
        di = (ai - (m7 >> p)) >> s

        return cr, ci, dr, di

    def bit_reverse(self, x, bits):
        """index bit reverse input array"""
        x_brev = np.empty(len(x), 'complex')
        for i, k in enumerate(x):
            binary = bin(i)
            reverse = binary[-1:1:-1]
            pos = int(reverse + (bits - len(reverse)) * '0', 2)
            x_brev[i] = x[pos]
        return x_brev

    def evaluate_slot(self, size, x_bits, w_bits, scaling='none', plot=True):
        """ Evaluate fft dynamic range performance using the slot noise (Xilinx datasheet) technique.
        See https://www.xilinx.com/support/documentation/ip_documentation/xfft/v9_0/pg109-xfft.pdf.
        However, the datasheet either leaves out critical info or displays wrong plots.
        As only noise in slot is of interest and precise noise power outside slot is not critical,
        the spectrum is set to 0 like in the datasheet."""

        # TODO: research on noise modeling and "full scale noise" ie. "where do I cut the bell curve??"
        sigma = 10  # cut off gauss distribution after sigma*std. deviation
        x_t = np.random.normal(0, sigma ** -1, size)  # +1j*np.random.normal(0,sigma**-1,size)  # draw random samples
        x_f = np.fft.fft(x_t)  # take fft or random samples
        x_f[int(len(x_f) / 2):(int(len(x_f) / 2) + int(len(x_f) / 20))] = 0  # cut slot
        x_t = np.fft.ifft(x_f)
        x_t = x_t * 2 ** (x_bits - 1)
        x_t = np.rint(x_t.real) + 1j * np.rint(x_t.imag)  # quantize to nr bits
        x_t = x_t * 2 ** -x_bits
        x_f_float = 20 * np.log10(abs(np.fft.fft(x_t)))  # ideal fft on quantized data
        x_f_float[:int(len(x_f) / 2)] = 0  # cut out region of interest like in xilinx datasheet
        x_f_float[(int(len(x_f) / 2) + int(len(x_f) / 20)):] = 0
        self.__init__(x_t, x_bits, w_bits)
        x_f_model = 20 * np.log10(abs(self.full_fft(scaling)))  # model fft on quantized data
        x_f_model[:int(len(x_f) / 2)] = 0  # cut out region of interest like in xilinx datasheet
        x_f_model[(int(len(x_f) / 2) + int(len(x_f) / 20)):] = 0
        if plot:
            plt.rc('font', size=18)
            plt.figure(1, [20, 10])
            plt.title('Slot noise performance:')
            plt.plot(x_f_float, label='ideal')
            plt.plot(x_f_model, label='model')
            plt.legend()
            plt.grid()
            plt.show()

        return x_f_model

    def evaluate_tone(self, size, x_bits, w_bits, scaling='none', plot=True):
        """Evaluate using full scale single complex tone. Calculate SNR."""
        tone = 3
        x_t = np.exp(1j * tone * np.linspace(0, 2 * np.pi, size, False))  # make fullscale amplitude 1 (+-0.5)
        x_t = ((x_t + np.random.normal(0, (2 ** -(x_bits - 1)) / np.sqrt(12),
                                       size)) * 2 ** x_bits)  # add one LSB qunatization noise
        x_t = np.rint(x_t.real) + 1j * np.rint(x_t.imag)  # quantize to nr bits
        x_t = x_t * 2 ** -x_bits
        x_f_float = abs(np.fft.fft(x_t)) / size  # ideal fft on quantized data
        x_f_float_db = 20 * np.log10(x_f_float)  # ideal fft on quantized data
        # fft_mod=fft_model(x_t,0,w_bits)         # make new model inside eval for convenience
        self.__init__(x_t, x_bits, w_bits, x_bits)
        x_f_model = abs((self.full_fft(scaling))) / size
        x_f_model_db = 20 * np.log10(x_f_model)  # model fft on quantized data
        if plot:
            plt.rc('font', size=18)
            plt.figure(1, [20, 10])
            plt.title('Single tone performance:')
            plt.plot(x_f_float_db.real, label='ideal')
            plt.plot(x_f_model_db.real, label='model')
            plt.legend()
            plt.grid()
            plt.show()
        snr_in = self.calc_snr(x_f_float, tone)
        snr_out = self.calc_snr(x_f_model, tone)
        print('---------------- \n tone eval:')
        print(f'input SNR: {snr_in} \t output SNR: {snr_out}')

    def evaluate_ifft(self, size, x_bits, w_bits, plot=True):
        """evaluate the ifft of a single tone without noise at the input"""
        tone = 1
        x_f = np.zeros(size, dtype='complex')
        x_f[tone] = 32767
        # single real tone at tone with max input ampl. will lead to and real cosine and complex sine in time domain
        self.__init__(x_f, w_bits)
        x_t = (self.full_fft(scaling='none', ifft=True))
        print(x_t)
        if plot:
            plt.rc('font', size=18)
            fig, ax = plt.subplots(1, 2, figsize=(15, 5))
            ax[0].set_title('ifft output:')
            ax[0].plot(x_t)
            x_f = 20 * np.log10(abs(np.fft.fft(x_t).real))  # with only one tone, the even/odd bins will see no noise..
            x_f[x_f == -np.inf] = np.min(x_f[x_f != -np.inf])  # set -inf values to lowest occurring value in plot
            ax[1].set_title('ifft output spectrum:')
            ax[1].plot(x_f.real)

        snr = self.calc_snr(x_t, tone, False)
        print('---------------- \n ifft eval:')
        print(f'SNR: {snr} ')

    @staticmethod
    def calc_snr(x, tone, freq_domain=True):
        """ helper to calc SNR of X at complex freq tone
        Data can be given in freq or time domain"""
        if not freq_domain:
            x = np.fft.fft(x)
        return 10 * np.log10((x[tone] * np.conj(x[tone])) / (np.sum(x * np.conj(x)) - x[tone] * np.conj(x[tone])))
        # calc SNR by integrating over noise
        # calculating SNR from spectrum makes a tiny mistake because some noise falls into the signal bin


if __name__ == "__main__":
    a = FftModel([0], 6, 18)
    a.evaluate_ifft(128, 16, 14)

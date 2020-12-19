from artiq.experiment import *
import numpy as np

# This is a volatile test script to exercise and evaluate
# some funny spectra using the phaser stft pulsegen :)

class Phaser(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.setattr_device("phaser0")

    @rpc(flags={"async"})
    def p(self, *p):
        print([hex(_ & 0xffffffff) for _ in p])

    def run(self):
        self.do()

    @kernel
    def do(self):
        # self.core.reset()
        self.core.break_realtime()
        for i in range(1):
            self.inner()

    def get_coeffs_triang(self) -> TList(TInt32):

        os = 90

        x = os - (abs(np.linspace(-1, 1, 31)) * os)
        coefs = np.roll(np.append(x, np.zeros(1024-len(x))), 0)

        return self.db_to_raw(coefs)

    def get_coeffs_triang2(self) -> TList(TInt32):

        os = 90

        x = os - (abs(np.linspace(-1, 1, 63)) * os)
        coefs = np.roll(np.append(x, np.zeros(1024-len(x))), 0)

        return self.db_to_raw(coefs)

    def get_coeffs_circle(self) -> TList(TInt32):

        os = 70

        x = np.linspace(-1, 1, 64)
        y1 = (np.sqrt((1 - x**2) * 300)) + os
        y2 = os - (np.sqrt((1 - x**2) * 300))
        coefs = np.empty((y1.size * 2), dtype=y1.dtype)
        coefs[0::2] = y1
        coefs[1::2] = y2
        coefs = np.roll(np.append(coefs, np.zeros(1024-len(coefs))), -32)

        return self.db_to_raw(coefs)

    def get_coeffs_snowman(self) -> TList(TInt32):

        os = 76

        x = np.linspace(-0.99, 0.99, 16)
        y1 = (np.sqrt((1 - x**2) * 16)) + os
        y2 = os - (np.sqrt((1 - x**2) * 16))

        os = 66

        x = np.linspace(-0.99, 0.99, 32)
        y3 = (np.sqrt((1 - x**2) * 40)) + os
        y4 = os - (np.sqrt((1 - x**2) * 40))

        os = 48

        x = np.linspace(-1, 1, 64)
        y5 = (np.sqrt((1 - x ** 2) * 270)) + os
        y6 = os - (np.sqrt((1 - x ** 2) * 270))


        coefs = np.zeros((y6.size * 6))
        coefs[0::6] = y5
        coefs[1::6] = 0
        coefs[(16*6):(48*6):6] = y3
        coefs[3+(8*6):3+(24*6):6] = 0
        coefs[((16+8)*6):((16+8+16)*6):6] = y1
        coefs[5+((8+4)*6):5+((16+4)*6):6] = 0

        coefs = np.roll(np.append(coefs, np.zeros(1024-len(coefs))), -32)

        return self.db_to_raw(coefs)

    def get_coeffs_sin(self) -> TList(TInt32):

        os = 73

        cos1 = (np.cos(np.linspace(0, 4*np.pi, 512)) * 13) + os
        sin2 = (np.sin(np.linspace(0, 2*np.pi, 128)) * 20) + os
        sin3 = (np.sin(np.linspace(0, 6 * np.pi, 128)) * 15) + os
        sin4 = (np.sin(np.linspace(0, 8 * np.pi, 128)) * 15) + os
        coefs = np.empty((cos1.size), dtype=cos1.dtype)
        coefs[0:512] = cos1
        #coefs[1::2] = 0#sin2
        # coefs[2::4] = sin3
        # coefs[3::4] = sin4
        coefs1 = np.append(coefs[:len(coefs)//2], np.zeros(512))
        coefs = np.append(coefs1, coefs[len(coefs)//2:])
        return self.db_to_raw(coefs)

    def db_to_raw(self, coef_db):
        return np.round(10**(coef_db / 20)).astype(int).tolist()

    @kernel
    def inner(self):
        f = self.phaser0
        f.init(debug=True)
        delay(.1 * ms)

        imag = [0 for _ in range(1024)]

        f.set_stft_enable_flag(1)

        delay(.1 * ms)

        for ch in range(2):
            f.channel[ch].set_att(0 * dB)

        f.pulsegen.set_pulsesettings(disable_window=1, gated_output=0)

        delay(.1 * ms)

        for i in range(4):  # branches + shaper
            f.pulsegen.clear_full_coef(i)
            delay(.1 * ms)


        for i in range(3):  # branches

            delay(.1 * ms)
            f.pulsegen.clear_full_coef(i)
            delay(.1 * ms)

            if i==0:
                real = self.get_coeffs_snowman()
                self.core.break_realtime()
                f.pulsegen.set_duc_frequency(i, 48.9 * MHz)
                f.pulsegen.set_duc_cfg(i, clr=0)
                delay(.1 * ms)
                f.pulsegen.set_interpolation_rate(i, 72)  # + i*4)
                delay(.1 * ms)
                f.pulsegen.set_shiftmask(i, 0x07)

            elif i==1:
                real = self.get_coeffs_triang()
                self.core.break_realtime()
                f.pulsegen.set_duc_frequency(i, 51.8 * MHz)
                f.pulsegen.set_duc_cfg(i, clr=0)
                delay(.1 * ms)
                f.pulsegen.set_interpolation_rate(i, 4)  # + i*4)
                delay(.1 * ms)
                f.pulsegen.set_shiftmask(i, 0x07)

            elif i==2:
                real = self.get_coeffs_triang2()
                self.core.break_realtime()
                f.pulsegen.set_duc_frequency(i, 44.7 * MHz)
                f.pulsegen.set_duc_cfg(i, clr=0)
                delay(.1 * ms)
                f.pulsegen.set_interpolation_rate(i, 8)  # + i*4)
                delay(.1 * ms)
                f.pulsegen.set_shiftmask(i, 0x07)

            else:
                real = self.get_coeffs_circle()

            delay(.1 * ms)
            f.pulsegen.send_full_coef(i, real, imag)
            delay(.1 * ms)
            f.pulsegen.start_fft(i)
            delay(.1 * ms)

        f.duc_stb()
        delay(.1 * ms)

        print("done")
        self.core.break_realtime()
        self.core.wait_until_mu(now_mu())
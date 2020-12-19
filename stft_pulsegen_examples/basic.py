from artiq.experiment import *
import numpy as np

# This is a volatile test script to exercise and evaluate some fun in the spectral domain :)

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

    @kernel
    def inner(self):
        f = self.phaser0
        f.init(debug=True)
        delay(.1 * ms)

        delay(.1*ms)

        f.set_stft_enable_flag(1)

        for ch in range(2):
            f.channel[ch].set_att(0*dB)

        f.pulsegen.set_pulsesettings(disable_window=1, gated_output=0)
        delay(.1*ms)
        imag = [0 for _ in range(1024)]

        real = [0 for i in range(1024)]
        real[:128] = [i*100 for i in range(128)]
        # real[-100] = 16000
        # real[0] = 0x7fff
        #real[300] = (2**16)-1000

        for i in range(4):  # branches + shaper
            f.pulsegen.clear_full_coef(i)
            delay(.1 * ms)

        for i in range(1):  # branch
            f.pulsegen.clear_full_coef(i)
            delay(.1 * ms)
            f.pulsegen.set_interpolation_rate(i, 2)#+ i*4)
            delay(.1 * ms)
            f.pulsegen.send_full_coef(i, real, imag)
            delay(.1 * ms)
            f.pulsegen.set_shiftmask(i, 0x1f)
            delay(.1 * ms)
            f.pulsegen.start_fft(i)
            delay(.1 * ms)
            if i <= 2:  # if branch
                f.pulsegen.set_duc_frequency(i, 100*MHz)
                f.pulsegen.set_duc_cfg(i, clr=0)
                delay(.1 * ms)
        f.duc_stb()
        delay(.1 * ms)


        print("done")
        self.core.break_realtime()
        self.core.wait_until_mu(now_mu())

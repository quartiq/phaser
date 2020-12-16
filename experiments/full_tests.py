from artiq.experiment import *
import numpy as np

# This is a volatile test script to exercise and evaluate some fun in the spectral domain :)

class Phaser(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.setattr_device("phaser0")

        # self.setattr_device("ttl0")
        # self.setattr_device("ttl1")

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

        for ch in range(2):
            f.channel[ch].set_att(0*dB)
            # f.channel[ch].set_duc_frequency_mu(0)
            f.channel[ch].set_duc_frequency(100*MHz)
            f.channel[ch].set_duc_phase(.25)
            f.channel[ch].set_duc_cfg(select=3, clr=0)
            delay(.1*ms)
        f.duc_stb()
        delay(.1*ms)

        f.pulsegen.set_pulsesettings(0)
        delay(.1*ms)
        imag = [0 for _ in range(1024)]

        real = [0 for i in range(1024)]
        real[:128] = [i*100 for i in range(128)]
        # real[-100] = 16000
        # real[0] = 32000
        # real[100] = 16000

        for i in range(3):  # branches + shaper
            f.pulsegen.clear_full_coef(i)
            delay(.1 * ms)
            f.pulsegen.set_interpolation_rate(i, 2 + i * 4 )#+ i*4)
            delay(.1 * ms)
            f.pulsegen.send_full_coef(i, real, imag)
            delay(.1 * ms)
            f.pulsegen.set_shiftmask(i, 0x07)
            delay(.1 * ms)
            f.pulsegen.start_fft(i)
            delay(.1 * ms)
            if i <= 2:  # if branch
                f.pulsegen.set_duc_frequency(i, (i*50 + 50) * MHz)

                f.pulsegen.set_duc_cfg(i, clr=0)
                delay(.1 * ms)
        f.duc_stb()
        delay(.1 * ms)

        real = [0 for i in range(1024)]
        real[-1] = 16000
        real[0] = 32000
        real[1] = 16000
        
        f.pulsegen.clear_full_coef(3)
        delay(.1 * ms)
        f.pulsegen.set_interpolation_rate(3, 600)
        delay(.1 * ms)
        f.pulsegen.send_full_coef(3, real, imag)
        delay(.1 * ms)
        f.pulsegen.set_shiftmask(3, 0xff)
        delay(.1 * ms)
        f.pulsegen.start_fft(3)
        delay(.1 * ms)

        print("done")
        self.core.break_realtime()
        self.core.wait_until_mu(now_mu())

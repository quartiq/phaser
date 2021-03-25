from artiq.experiment import *

# This is a volatile test script to exercise and evaluate the deterministic timing
# of the stft pulsegen. Emits a ttl pulse and 3 stft pulses using all 3 branches
# and a hann shaped window.

class Phaser(EnvExperiment):
    def build(self):
        self.setattr_device("core")
        self.setattr_device("phaser0")
        self.setattr_device("ttl0")
        self.setattr_device("ttl1")

    @rpc(flags={"async"})
    def p(self, *p):
        print([hex(_ & 0xffffffff) for _ in p])

    def run(self):
        self.do()

    @kernel
    def do(self):
        #self.core.reset()
        self.core.break_realtime()
        for i in range(1):
            self.inner()

    @kernel
    def inner(self):
        f = self.phaser0
        ttl0 = self.ttl0

        f.init(debug=True)
        delay(.1 * ms)

        for ch in range(1):
            f.channel[ch].set_att(0 * dB)
            # f.channel[ch].set_duc_frequency_mu(0)
            f.channel[ch].set_duc_frequency(190.598551 * MHz)
            f.channel[ch].set_duc_phase(.25)
            f.channel[ch].set_duc_cfg(select=0, clr=0)
            delay(.1 * ms)
            for osc in range(5):
                ftw = (osc + 1) * 1.875391 * MHz
                asf = (osc + 1) * .066
                # if osc != 4:
                #    asf = 0.
                # else:
                #    asf = .9
                #    ftw = 9.5*MHz
                # f.channel[ch].oscillator[osc].set_frequency_mu(0)
                f.channel[ch].oscillator[osc].set_frequency(ftw)
                delay(.1 * ms)
                f.channel[ch].oscillator[osc].set_amplitude_phase(asf, phase=.25, clr=0)
                delay(.1 * ms)
        f.duc_stb()
        delay(.1 * ms)

        f.set_stft_enable_flag(1)

        f.pulsegen.set_pulsesettings(disable_window=0, gated_output=1)
        f.pulsegen.set_nr_repeats(3)
        delay(.1 * ms)
        imag = [0 for _ in range(1024)]
        real = [0 for i in range(1024)]
        real[:128] = [i * 100 for i in range(128)]
        # real[-100] = 16000
        # real[0] = 32000
        # real[100] = 16000

        for i in range(3):  # branches
            f.pulsegen.clear_full_coef(i)
            delay(.1 * ms)
            f.pulsegen.set_interpolation_rate(i, 2 + i * 4)  # + i*4)
            delay(.1 * ms)
            f.pulsegen.send_full_coef(i, real, imag)
            delay(.1 * ms)
            f.pulsegen.set_shiftmask(i, 0x07)
            delay(.1 * ms)
            f.pulsegen.start_fft(i)
            delay(.1 * ms)
            if i <= 2:  # if branch
                f.pulsegen.set_duc_frequency(i, (i*50 + 50) * MHz)

                f.pulsegen.set_duc_cfg(i, clr=0, clr_once=1)
                delay(.1 * ms)
        f.duc_stb()
        delay(.1 * ms)

        real = [0 for i in range(1024)]
        real[-1] = -16000
        real[0] = 32000
        real[1] = -16000

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

        f.pulsegen.get_frame_timestamp()
        t = now_mu()+(int64(f.pulsegen.tframe) * 20000)
        loopdelay = 200000 * f.pulsegen.tframe
        for i in range(100000):
            at_mu(t)
            t = t + loopdelay
            ttl0.pulse(1 * us)
            f.pulsegen.trigger()


        print("done")
        self.core.break_realtime()
        self.core.wait_until_mu(now_mu())

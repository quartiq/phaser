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

    def get_coeffs(self) -> TList(TInt32):
        os = 75
        sin1 = (np.sin(np.linspace(0, 4*np.pi, 128)) * 20) + os
        sin2 = (np.sin(np.linspace(0, 2*np.pi, 128)) * 20) + os
        sin3 = (np.sin(np.linspace(0, 6 * np.pi, 128)) * 20) + os
        sin4 = (np.sin(np.linspace(0, 8 * np.pi, 128)) * 20) + os
        coefs = np.empty((sin1.size*4), dtype=sin1.dtype)
        coefs[0::4] = 90
        coefs[1::4] = 1#in2
        coefs[2::4] = 1#sin3
        coefs[3::4] = 1#sin4
        coefs1 = np.append(coefs[:len(coefs)//2], np.zeros(512))
        coefs = np.append(coefs1, coefs[len(coefs)//2:])
        return self.db_to_raw(coefs)

    def db_to_raw(self, coef_db):
        return np.round(10**(coef_db / 20)).astype(int).tolist()
        #return [i*20 for i in range(256)]

    @kernel
    def inner(self):
        f = self.phaser0
        # ttl0 = self.ttl0
        # ttl1 = self.ttl1


        f.init(debug=True)
        #f.set_cfg(clk_sel=f.clk_sel)
        delay(.1 * ms)

        for ch in range(2):
            f.channel[ch].set_att(0*dB)
            # f.channel[ch].set_duc_frequency_mu(0)
            f.channel[ch].set_duc_frequency(100*MHz)
            f.channel[ch].set_duc_phase(.25)
            f.channel[ch].set_duc_cfg(select=2, clr=0)
            delay(.1*ms)

        f.duc_stb()
        delay(.1*ms)
        f.pulsegen.set_pulsesettings(0)
        delay(.1*ms)
        imag = [0 for _ in range(1024)]
        real = [0 for _ in range(1024)]
        real[-1] = 16000
        real[0] = 32000
        real[1] = 16000
        self.core.break_realtime()
        #print(real)

        self.core.break_realtime()

        # f.pulsegen.set_pulsesettings(1)
        # f.pulsegen.set_nr_repeats(1)

        f.write8(0x32, 0)
        #delay(.1 * ms)
        f.pulsegen.clear_full_coef(0)
        delay(1 * ms)
        f.pulsegen.clear_full_coef(1)
        delay(1 * ms)
        f.pulsegen.clear_full_coef(2)
        delay(.1*ms)
        # f.pulsegen.send_coef(3, 1, [0x4000], [0x4000])
        # delay(1 * ms)
        f.pulsegen.clear_full_coef(3)
        delay(1 * ms)

        f.pulsegen.set_interpolation_rate(0, 4)
        delay(.1 * ms)
        f.pulsegen.set_interpolation_rate(1, 2)
        delay(.1 * ms)
        f.pulsegen.set_interpolation_rate(2, 20)
        delay(.1 * ms)
        f.pulsegen.set_interpolation_rate(3, 100)
        delay(.1 * ms)


        # f.pulsegen.send_full_coef(3, real, imag)
        # delay(.1 * ms)
        # f.pulsegen.send_full_coef(0, real, imag)
        # delay(.1 * ms)
        f.pulsegen.send_coef(0, 0, [0x0], [0x10000])
        delay(.1 * ms)
        # f.pulsegen.send_coef(2, 8, [0x4000, 0x2000], [0x4000, 0x2000])
        # delay(.1 * ms)

        f.pulsegen.set_shiftmask(0, 0xff)
        delay(.1*ms)
        f.pulsegen.set_shiftmask(1, 0xff)
        delay(.1 * ms)
        f.pulsegen.set_shiftmask(2, 0xff)
        delay(.1 * ms)
        f.pulsegen.set_shiftmask(3, 0xff)
        delay(.1 * ms)

        f.pulsegen.start_fft(0)
        delay(.1 * ms)
        f.pulsegen.start_fft(1)
        delay(.1 * ms)
        f.pulsegen.start_fft(2)
        delay(.1 * ms)
        f.pulsegen.start_fft(3)
        delay(.1 * ms)

        # f.pulsegen.get_frame_timestamp()
        # at_mu(int64(f.pulsegen.frame_tstamp + 0xffffff))
        # delay_mu(int64(f.pulsegen.tframe) * 20)
        # t = now_mu()
        # loopdelay = 20000 * f.pulsegen.tframe
        # for i in range(100000):
        #     at_mu(t)
        #     t = t + loopdelay
        #     ttl0.pulse(1 * us)
        #     f.pulsegen.trigger()

        for ch in range(2):
            for addr in range(8):
                r = f.channel[ch].trf_read(addr)
                delay(.1*ms)
                self.p(r)
                self.core.break_realtime()

        alarm = f.dac_read(0x05)
        self.p(alarm)
        self.core.break_realtime()
        # This will set the TRFs and the DAC to sleep.
        # Saves power and temperature rise but oviously disables RF as
        # well.
        # f.set_cfg(dac_sleep=1, trf0_ps=1, trf1_ps=1)
        self.core.wait_until_mu(now_mu())

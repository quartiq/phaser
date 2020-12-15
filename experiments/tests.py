from artiq.experiment import *
import numpy as np

# This is a volatile test script to exercise and evaluate some functionality of
# Phaser through ARTIQ.

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

    def get_coeffs(self) -> TList(TInt32):
        os = 75
        sin1 = (np.sin(np.linspace(0, 4*np.pi, 128)) * 20) + os
        sin2 = np.zeros(128)#(np.sin(np.linspace(0, 2*np.pi, 128)) * 20) + os
        sin3 = np.zeros(128)#(np.sin(np.linspace(0, 6 * np.pi, 128)) * 20) + os
        sin4 = np.zeros(128)#(np.sin(np.linspace(0, 8 * np.pi, 128)) * 20) + os
        coefs = np.empty((sin1.size*4), dtype=sin1.dtype)
        coefs[0::4] = sin1
        coefs[1::4] = sin2
        coefs[2::4] = sin3
        coefs[3::4] = sin4
        return self.db_to_raw(coefs)

    def db_to_raw(self, coef_db):
        return np.round(10**(coef_db / 20)).astype(int).tolist()
        #return [i*20 for i in range(256)]

    @kernel
    def inner(self):
        f = self.phaser0


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
        f.pulsegen.set_pulsesettings(2)
        delay(1 * ms)
        imag = [0 for _ in range(512)]
        real = self.get_coeffs()
        self.core.break_realtime()
        print(real)

        self.core.break_realtime()
        f.pulsegen.clear_full_coef()
        #f.pulsegen.send_coef(1, [0x4000], [0x4000])
        delay(1 * ms)

        f.pulsegen.set_interpolation_rate(2)
        delay(1 * ms)

        delay(.1 * ms)

        f.pulsegen.send_full_coef(real, imag)
        delay(.1 * ms)

        f.pulsegen.set_shiftmask(0x03)
        delay(1*ms)

        f.pulsegen.start_fft()
        delay(1 * ms)

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

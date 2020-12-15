from artiq.experiment import *

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
            for osc in range(5):
                ftw = (osc + 1)*1.875391*MHz
                asf = (osc + 1)*.066
                #if osc != 4:
                #    asf = 0.
                #else:
                #    asf = .9
                #    ftw = 9.5*MHz
                # f.channel[ch].oscillator[osc].set_frequency_mu(0)
                f.channel[ch].oscillator[osc].set_frequency(ftw)
                delay(.1*ms)
                f.channel[ch].oscillator[osc].set_amplitude_phase(asf, phase=.25, clr=0)
                delay(.1*ms)
        f.duc_stb()
        delay_mu(8)
        a = 64
        imag = [0 for _ in range(a)]
        real = [i*0x100 for i in range(a)]
        # real = [0,0,0]
        # imag = [0,0,0]

        # f.pulsegen.stage_coef_adr(64)
        # delay_mu(800)
        # f.pulsegen.stage_coef_data(0, 0x2000, 0)
        # delay_mu(800)
        # f.pulsegen.send_frame()
        # delay_mu(800)

        f.pulsegen.clear_full_coef()
        delay(1 * ms)

        f.pulsegen.set_interpolation_rate(8)
        delay(1 * ms)

        # f.pulsegen.stage_coef_adr(64)
        # delay_mu(800)
        # f.pulsegen.send_coef(20, [0x3fff,0xef00,0,0x2000], [0x3fff,0x0100,0,0xd000])
        #f.pulsegen.send_coef(61, [0x2000,0x2000,0x2000,0x2000], [0x000,0x000,0x000,0x000])
        delay(.1 * ms)

        f.pulsegen.send_full_coef(real, imag)
        delay(.1 * ms)

        f.pulsegen.set_shiftmask(0x00)
        delay(1*ms)

        #f.pulsegen.send_coef(0, [0x0,0x0,0,0x0000, 0x0000], [0x0,0x0000,0,0x0000, 0])



        f.pulsegen.start_fft()
        # delay(1000 * ms)
        # f.pulsegen.set_interpolation_rate(500)
        delay(1 * ms)


        # r=2
        # for i in range(50):
        #     f.pulsegen.set_interpolation_rate(r)
        #     r=(r+100)%500
        #     delay(500 * ms)


        # f.pulsegen.send_full_coef(imag, real)
        # delay(1 * ms)

        # f.pulsegen.clear_staging_area()
        # delay_mu(8)
        # f.pulsegen.stage_coef_adr(0)
        # delay_mu(5000)
        # f.pulsegen.send_frame()
        # delay_mu(8)
        # f.pulsegen.stage_coef_adr(0)
        # delay_mu(800)
        # # f.pulsegen.stage_coef_data(0, 0x7fff, 0)
        # # delay_mu(800)
        # f.pulsegen.send_frame()
        # delay_mu(800)



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

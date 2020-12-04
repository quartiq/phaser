from artiq.experiment import *

# This is a volatile test script to exercise and evaluate some functionality of
# Phaser through ARTIQ.

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
        ttl1 = self.ttl1


        f.init(debug=True)
        #f.set_cfg(clk_sel=f.clk_sel)
        delay(.1 * ms)

        for ch in range(2):
            f.channel[ch].set_att(0*dB)
            # f.channel[ch].set_duc_frequency_mu(0)
            f.channel[ch].set_duc_frequency(200*MHz)
            f.channel[ch].set_duc_phase(.25)
            f.channel[ch].set_duc_cfg(select=3, clr=0)

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
        f.pulsegen.clear_full_coef()
        delay(1 * ms)
        delay_mu(8)
        a=32
        real = [0x3000 for i in range(a)]
        f.pulsegen.set_pulsesettings(1)
        f.pulsegen.set_nr_repeats(10)
        delay(0.1*ms)
        f.pulsegen.send_full_coef(real, real)
        delay(.01 * ms)
        f.pulsegen.get_frame_timestamp()
        at_mu(int64(f.pulsegen.frame_tstamp+0xffffff))
        delay_mu(int64(f.pulsegen.tframe)*20)
        t = now_mu()
        loopdelay = 200 * f.pulsegen.tframe
        for i in range(10000000):
            at_mu(t)
            t = t+loopdelay
            ttl0.pulse(1*us)
            f.pulsegen.trigger()



        delay(1*ms)

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

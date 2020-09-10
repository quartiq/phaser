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
        t_frame = 10*8*4

        delay(1*ms)
        f.init()
        f.set_leds(0x3f)
        f.set_cfg(dac_resetb=0, att0_rstn=0, att1_rstn=0)  # reset dac
        f.set_cfg(clk_sel=1)
        f.set_fan(80)
        assert f.get_crc_err() < 20  # startup errors
        delay(.1*ms)

        delay(.5*ms)
        # test att write read
        f.att_write(0, 0x55)
        assert f.att_read(0) == 0x55
        delay(.1*ms)
        assert f.att_read(0) == 0x55
        delay(.1*ms)
        f.att_write(0, 0xff)
        f.att_write(1, 0xff)

        delay(.1*ms)
        # sif4_enable
        f.dac_write(0x02, 0x0082)
        # version
        assert f.dac_read(0x7f) == 0x5409
        delay(.1*ms)
        # config0 reset
        assert f.dac_read(0x00) == 0x049c
        delay(.1*ms)

        temp = f.dac_read(0x06, div=250) >> 8
        delay(.1*ms)
        assert temp >= 20 and temp <= 85

        # iotest
        delay(.5*ms)
        # p = [0xffff, 0xffff, 0x0000, 0x0000]  # test channel
        # p = [0xaa55, 0x55aa, 0x55aa, 0xaa5a]  # test iq
        # p = [0xaa55, 0xaa55, 0x55aa, 0x55aa]  # test byte
        p = [0x7a7a, 0xb6b6, 0xeaea, 0x4545]  # ds pattern a
        # p = [0x1a1a, 0x1616, 0xaaaa, 0xc6c6]  # ds pattern b
        for addr in range(len(p)):
            f.dac_write(0x25 + addr, p[addr])
            f.dac_write(0x29 + addr, p[addr])
        delay(.1*ms)
        for ch in range(2):
            f.set_duc_cfg(ch, select=1)  # test
            # dac test data is i msb, q lsb
            f.set_dac_test(ch, p[2*ch] | (p[2*ch + 1] << 16))
        f.dac_write(0x01, 0x8000)  # iotest_ena
        for idly in [0]:  # range(2)
            for dly in [0]:  # range(8)
                if idly:
                    dly = dly << 3
                f.dac_write(0x24, dly << 10)
                f.dac_write(0x04, 0x0000)  # clear iotest_result
                f.dac_write(0x05, 0x0000)  # clear alarms
                delay(.1*ms)
                alarm = f.dac_read(0x05)
                delay(.1*ms)
                if alarm & 0x0080:  # alarm_from_iotest
                    self.p(f.dac_read(0x04))
                    # raise ValueError("iotest fail")
                self.core.break_realtime()
        f.dac_write(0x24, 0)

        delay(.5*ms)
        f.dac_write(0x00, 0x019c)  # I=2, fifo, clkdiv_sync, qmc off
        f.dac_write(0x01, 0x040e)  # fifo alarms, parity
        f.dac_write(0x02, 0x70a2)  # clk alarms, sif4, nco off, mix, mix_gain, 2s
        f.dac_write(0x03, 0xa000)  # coarse dac 20.6 mA
        f.dac_write(0x07, 0x40c1)  # alarm mask
        f.dac_write(0x09, 0xa000)  # fifo_offset
        f.dac_write(0x0d, 0x0000)  # fmix, no cmix
        f.dac_write(0x14, 0x5431)  # fine nco ab
        f.dac_write(0x15, 0x0323)  # coarse nco ab
        f.dac_write(0x16, 0x5431)  # fine nco cd
        f.dac_write(0x17, 0x0323)  # coarse nco cd
        f.dac_write(0x18, 0x2c60)  # P=4, pll run, single cp, pll_ndivsync
        f.dac_write(0x19, 0x8404)  # M=8 N=1
        f.dac_write(0x1a, 0xfc00)  # pll_vco=63
        delay(.1*ms)  # slack
        f.dac_write(0x1b, 0x0800)  # int ref, fuse
        f.dac_write(0x1e, 0x9999)  # qmc sync from sif and reg
        f.dac_write(0x1f, 0x9982)  # mix sync, nco sync, istr is istr, sif_sync
        f.dac_write(0x20, 0x2400)  # fifo sync ISTR-OSTR
        f.dac_write(0x22, 0x1bb1)  # swap ab and cd dacs
        f.dac_write(0x24, 0x0000)  # clk and data delays

        delay(1*ms)  # lock pll
        lvolt = f.dac_read(0x18) & 7
        delay(.1*ms)
        assert lvolt >= 2 and lvolt <= 5
        f.dac_write(0x20, 0x0000)  # stop fifo sync
        f.dac_write(0x05, 0x0000)  # clear alarms
        delay(1*ms)  # run it
        alarm = f.get_sta() & 1
        delay(.1*ms)
        if alarm:
            alarm = f.dac_read(0x05)
            self.p(alarm)
            # raise ValueError("alarm")
            self.core.break_realtime()

        a = [0x00007fff, 0x00007fff]
        for ch in range(2):
            f.set_duc_cfg(ch, select=1)
            f.set_dac_test(ch, a[ch])
            # assert f.get_dac_data(ch) == a[ch]
            delay(.1*ms)

        for ch in range(2):
            f.set_duc_frequency_mu(ch, 0x1357911)
            f.set_duc_phase_mu(ch, 0x0000)
            f.set_duc_cfg(ch, select=0)
            for osc in range(5):
                ftw = ((osc + 1) << 28) + 0x1234567
                asf = (osc + 1) << 11
                #if osc != 4:
                #    asf = 0
                #else:
                #    asf = 0x7fff
                #    ftw = 0x0  #1234567
                f.set_frequency_mu(ch, osc, ftw)
                delay(1*us)
                f.set_amplitude_phase_mu(ch, osc, asf,
                                         pow=0x0000, clr=0)
                delay(1*us)
                delay(.1*ms)
        f.duc_stb()

        for ch in range(2):
            delay(.2*ms)
            f.trf_write(ch, 0x601002a9)
            f.trf_write(ch, 0x8880348a)
            f.trf_write(ch, 0x0000000b)
            f.trf_write(ch, 0x4a00800c)
            f.trf_write(ch, 0x0d03a28d)
            f.trf_write(ch, 0x9d90100e)
            f.trf_write(ch, 0xd041100f)
            delay(1*ms)  # lock
            ld = f.get_sta() & (2 << ch)
            assert ld != 0
            delay(.1*ms)

            for addr in range(8):
                r = f.trf_read(ch, addr)
                delay(.1*ms)
                self.p(r)
                self.core.break_realtime()

        # f.set_cfg(dac_sleep=1, trf0_ps=1, trf1_ps=1)
        self.core.wait_until_mu(now_mu())

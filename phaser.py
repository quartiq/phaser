from migen import *
from misoc.cores.spi2 import SPIMachine, SPIInterface
from misoc.cores.duc import PhasedDUC

from crg import CRG
from link import Link
from decode import Decode, Register
from dac_data import DacData


class PWM(Module):
    def __init__(self, pin):
        cnt = Signal(12, reset_less=True)
        self.duty = Signal.like(cnt)
        self.sync += [
            cnt.eq(cnt + 1),
            If(cnt == 0,
                pin.eq(1),
            ),
            If(cnt == self.duty,
                pin.eq(0),
            ),
        ]


class Phaser(Module):
    def __init__(self, platform):
        eem = platform.request("eem", 0)
        self.submodules.link = Link(eem)
        self.submodules.crg = CRG(platform, link=self.link.phy.clk)
        platform.add_period_constraint(eem.data0_p, 4.*8)
        platform.add_false_path_constraint(eem.data0_p, self.crg.cd_sys2.clk)
        self.submodules.decoder = Decode(
            b_sample=14, n_channel=2, n_mux=8, t_frame=8*10)
        self.comb += [
            self.decoder.frame.eq(self.link.checker.frame),
            self.decoder.stb.eq(self.link.checker.frame_stb),
            # 2 miso bits max rtt latency
            Cat(self.link.checker.response[2*8:]).eq(
                Cat([Replicate(d, 8) for d in self.decoder.response])),
        ]

        self.decoder.map_registers([
            (0x00,),
            # Sinara board id (19) as assigned in the Sinara EEPROM layout
            ("board_id", Register(write=False)),
            # hardware revision and variant
            ("hw_rev", Register(write=False)),
            # gateware revision
            ("gw_rev", Register(write=False)),
            # configuration (clk_sel, dac_resetb, dac_sleep,
            # dac_txena, trf0_ps, trf1_ps, att0_rstn, att1_rstn)
            ("cfg", Register()),
            # status (dac_alarm, trf0_ld, trf1_ld, term0_stat,
            # term1_stat, spi_idle)
            ("sta", Register(write=False)),
            # frame crc error counter
            ("crc_err", Register(write=False)),
            # led configuration
            ("led", Register(width=6)),
            # fan pwm duty cycle
            ("fan", Register()),
            # DUC settings update strobe
            ("duc_stb", Register(write=False, read=False)),
            # ADC gain configuration (pgia0_gain, pgia1_gain)
            ("adc_cfg", Register(width=4)),
            # spi configuration (offline, end, clk_phase, clk_polarity,
            # half_duplex, lsb_first)
            ("spi_cfg", Register()),
            # spi divider and transaction length (div(5), len(3))
            ("spi_divlen", Register()),
            # spi chip select (dac, trf0, trf1, att0, att1)
            ("spi_sel", Register()),
            # spi mosi data and transaction start/continue
            ("spi_datw", Register(read=False)),
            # spi readback data, available after each transaction
            ("spi_datr", Register(write=False)),
            ("reserved0", Register(read=False, write=False)),
            (0x10,),
            # digital upconverter (duc) configuration
            # (accu_clr, accu_clr_once, data_select (0: duc, 1: test))
            ("duc0_cfg", Register()),
            ("duc0_reserved", Register(read=False, write=False)),
            # duc frequency tuning word (msb first)
            ("duc0_f", Register(), Register(), Register(), Register()),
            # duc phase offset word
            ("duc0_p", Register(), Register()),
            # dac data
            ("dac0_data", Register(write=False), Register(write=False),
                          Register(write=False), Register(write=False)),
            # dac test data for duc_cfg:data_select == 1
            ("dac0_test", Register(), Register(), Register(), Register()),
            (0x20,),
            # digital upconverter (duc) configuration
            # (accu_clr, accu_clr_once, data_select (0: duc, 1: test))
            ("duc1_cfg", Register()),
            ("duc1_reserved", Register(read=False, write=False)),
            # duc frequency tuning word (msb first)
            ("duc1_f", Register(), Register(), Register(), Register()),
            # duc phase offset word
            ("duc1_p", Register(), Register()),
            # dac data
            ("dac1_data", Register(write=False), Register(write=False),
                          Register(write=False), Register(write=False)),
            # dac test data for duc_cfg:data_select == 1
            ("dac1_test", Register(), Register(), Register(), Register()),
        ])

        dac_ctrl = platform.request("dac_ctrl")
        trf_ctrl = [platform.request("trf_ctrl") for _ in range(2)]
        att_rstn = [platform.request("att_rstn") for _ in range(2)]
        adc_ctrl = platform.request("adc_ctrl")
        self.comb += [
            self.decoder.get("board_id", "read").eq(19),  # Sinara.boards.index("Phaser")
            self.decoder.get("hw_rev", "read").eq(Cat(
                platform.request("hw_rev"), platform.request("hw_variant"))),
            self.decoder.get("gw_rev", "read").eq(0x01),
            Cat([platform.request("user_led", i) for i in range(6)]).eq(
                self.decoder.get("led", "write")),
            Cat(platform.request("clk_sel"), dac_ctrl.resetb, dac_ctrl.sleep,
                dac_ctrl.txena, trf_ctrl[0].ps, trf_ctrl[1].ps,
                att_rstn[0], att_rstn[1]).eq(self.decoder.get("cfg", "write")),
            Cat(adc_ctrl.gain0, adc_ctrl.gain1).eq(
                self.decoder.get("adc_cfg", "write")),
            self.decoder.get("crc_err", "read").eq(self.link.checker.crc_err),
        ]

        fan = platform.request("fan_pwm")
        fan.reset_less = True
        self.submodules.fan = PWM(fan)
        self.comb += self.fan.duty[-8:].eq(self.decoder.get("fan", "write"))

        self.submodules.spiint = SPIInterface(
            platform.request("dac_spi"),
            platform.request("trf_spi", 0),
            platform.request("trf_spi", 1),
            platform.request("att_spi", 0),
            platform.request("att_spi", 1),
        )
        self.submodules.spi = SPIMachine(data_width=8, div_width=8)
        self.comb += [
            self.decoder.get("sta", "read").eq(Cat(
                dac_ctrl.alarm, trf_ctrl[0].ld, trf_ctrl[1].ld,
                adc_ctrl.term_stat, self.spi.idle)),
            self.spi.load.eq(self.decoder.registers["spi_datw"][0].bus.we),
            self.spi.reg.pdo.eq(self.decoder.registers["spi_datw"][0].bus.dat_w),
            # self.spi.readable, self.spi.writable, self.spi.idle,
            self.spiint.cs.eq(self.decoder.get("spi_sel", "write")),
            self.spiint.cs_polarity.eq(0),  # all active low
            Cat(self.spi.cg.div[3:], self.spi.length).eq(
                self.decoder.get("spi_divlen", "write")),
            Cat(self.spiint.offline, self.spi.end,
                self.spi.clk_phase, self.spiint.clk_polarity,
                self.spiint.half_duplex, self.spi.reg.lsb_first).eq(
                    self.decoder.get("spi_cfg", "write")),
            self.spiint.cs_next.eq(self.spi.cs_next),
            self.spiint.clk_next.eq(self.spi.clk_next),
            self.spiint.ce.eq(self.spi.ce),
            self.spiint.sample.eq(self.spi.reg.sample),
            self.spi.reg.sdi.eq(self.spiint.sdi),
            self.spiint.sdo.eq(self.spi.reg.sdo),
        ]
        # relax timing on this one
        self.sync += [
            self.decoder.get("spi_datr", "read").eq(self.spi.reg.pdi),
        ]

        self.submodules.data = DacData(platform.request("dac_data"))
        self.comb += [
            # sync istr counter every frame
            self.data.data_sync.eq(self.decoder.zoh.body_stb),
        ]
        for i in range(2):
            duc = PhasedDUC(n=2, pwidth=19, fwidth=32, zl=10)
            self.submodules += duc
            cfg = self.decoder.get("duc{}_cfg".format(i), "write")
            self.sync += [
                # keep accu cleared
                duc.clr.eq(cfg[0]),
                If(self.decoder.registers["duc_stb"][0].bus.we,
                    # clear accu once
                    If(cfg[1],
                        duc.clr.eq(1),
                    ),
                    duc.f.eq(self.decoder.get("duc{}_f".format(i), "write")),
                    duc.p[2:].eq(self.decoder.get("duc{}_p".format(i), "write")),
                ),
            ]
            for j, (ji, jo) in enumerate(zip(duc.i, duc.o)):
                self.comb += [
                    ji.i[2:].eq(self.decoder.zoh.sample[i].i),
                    ji.q[2:].eq(self.decoder.zoh.sample[i].q),
                ]
                self.sync += [
                    If(cfg[2:4] == 0,  # ducx_cfg_sel
                        self.data.data[2*j][i].eq(jo.i),
                        self.data.data[2*j + 1][i].eq(jo.q),
                    )
                ]

            self.sync += [
                If(cfg[2:4] == 1,
                    # i is lsb, q is msb
                    Cat([d[i] for d in self.data.data]).eq(Replicate(
                        self.decoder.get("dac{}_test".format(i), "write"), 2))
                )
            ]
        self.comb += [
            self.decoder.get("dac0_data", "read").eq(Cat(
                self.data.data[0][0], self.data.data[1][0])),
            self.decoder.get("dac1_data", "read").eq(Cat(
                self.data.data[0][1], self.data.data[1][1])),
        ]

        self.comb += [
            Cat([platform.request("test_point", i) for i in range(6)]).eq(Cat(
                ClockSignal("clk125"),
                ClockSignal("link"),
                #ClockSignal(),
                ResetSignal(),
                #self.link.slip.bitslip,
                #self.link.unframe.data[0],
                #self.link.unframe.data[1],
                #self.link.unframe.clk_stb,
                #self.link.unframe.marker_stb,
                #self.link.unframe.end_of_frame,
                self.link.checker.frame_stb,
                # self.decoder.bus.bus.we,
                # self.decoder.bus.bus.re,
                # self.decoder.bus.bus.adr[0],
                self.link.checker.miso,
                # self.data.data_sync,
                # self.data.istr,
                dac_ctrl.alarm,
            ))
        ]


if __name__ == "__main__":
    from platform import Platform
    platform = Platform(load=True)
    test = Phaser(platform)
    platform.build(test, build_name="phaser")

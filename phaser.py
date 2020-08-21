from migen import *
from misoc.cores.spi2 import SPIMachine, SPIInterface

from crg import CRG
from link import Link
from decode import Decode, Register
from duc import PhasedDUC
from dac_data import DacData


class PWM(Module):
    def __init__(self, pin):
        cnt = Signal(10, reset_less=True)
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
        ]

        self.decoder.map_registers([
            (0x00,),
            ("id", Register(write=False)),
            ("hw_rev", Register(write=False)),
            ("gw_rev", Register(write=False)),
            ("cfg", Register()),
            ("sta", Register(write=False)),
            ("led", Register(width=6)),
            ("fan", Register()),
            ("duc_cfg", Register()),
            ("duc_stb", Register(write=False, read=False)),
            ("adc_cfg", Register(width=4)),
            ("spi_cfg", Register()),
            ("spi_div", Register()),
            ("spi_sel", Register()),
            ("spi_datw", Register(read=False)),
            ("spi_datr", Register(write=False)),
            (0x10,),
            ("duc0_f", Register(), Register(), Register(), Register()),
            ("duc0_p", Register(), Register()),
            ("dac0_data", Register(write=False), Register(write=False),
                          Register(write=False), Register(write=False)),
            ("dac0_test", Register(read=False), Register(read=False),
                          Register(read=False), Register(read=False)),
            (0x20,),
            ("duc1_f", Register(), Register(), Register(), Register()),
            ("duc1_p", Register(), Register()),
            ("dac1_data", Register(write=False), Register(write=False),
                          Register(write=False), Register(write=False)),
            ("dac1_test", Register(read=False), Register(read=False),
                          Register(read=False), Register(read=False)),
        ])

        dac_ctrl = platform.request("dac_ctrl")
        trf_ctrl = [platform.request("trf_ctrl") for _ in range(2)]
        att_rstn = [platform.request("att_rstn") for _ in range(2)]
        adc_ctrl = platform.request("adc_ctrl")
        self.comb += [
            self.decoder.get("id", "read").eq(19),  # Sinara.boards.index("Phaser")
            self.decoder.get("hw_rev", "read").eq(Cat(
                platform.request("hw_rev"), platform.request("hw_variant"))),
            self.decoder.get("gw_rev", "read").eq(0x01),
            Cat([platform.request("user_led", i) for i in range(6)]).eq(
                self.decoder.get("led", "write")),
            Cat(platform.request("clk_sel"), dac_ctrl.resetb, dac_ctrl.sleep,
                dac_ctrl.txena, trf_ctrl[0].ps, trf_ctrl[1].ps,
                att_rstn[0], att_rstn[1]).eq(self.decoder.get("cfg", "write")),
            self.decoder.get("sta", "read")[:6].eq(Cat(
                dac_ctrl.alarm, trf_ctrl[0].ld, trf_ctrl[1].ld,
                adc_ctrl.term_stat)),  # 6, 7 for spi machine
            Cat(adc_ctrl.gain0, adc_ctrl.gain1).eq(
                self.decoder.get("adc_cfg", "write")),
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
            self.decoder.get("sta", "read")[6:].eq(Cat(
                self.spi.idle, self.spi.writable)),
            self.spi.reg.pdo.eq(self.decoder.get("spi_datw", "write")),
            self.decoder.get("spi_datr", "read").eq(self.spi.reg.pdi),
            # self.spi.readable, self.spi.writable, self.spi.idle,
            self.spiint.cs.eq(self.decoder.get("spi_sel", "write")),
            self.spiint.cs_polarity.eq(0),  # all active low
            self.spi.length.eq(8 - 1),  # always
            self.spi.cg.div.eq(self.decoder.get("spi_div", "write")),
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
        self.sync += [
            # load on write
            self.spi.load.eq(self.decoder.registers["spi_datw"][0].bus.we),
        ]

        self.submodules.data = DacData(platform.request("dac_data"))
        self.comb += [
            self.data.data_sync.eq(self.decoder.zoh.sample_mark),
        ]
        for i in range(2):
            duc = PhasedDUC(n=2, pwidth=18, fwidth=32)
            self.submodules += duc
            self.sync += [
                # keep accu cleared
                duc.clr.eq(self.decoder.get("duc_cfg", "write")[i]),
                If(self.decoder.registers["duc_stb"][0].bus.we,
                    # clear accu once
                    If(self.decoder.get("duc_cfg", "write")[2 + i],
                        duc.clr.eq(1),
                    ),
                    duc.f.eq(self.decoder.get("duc{}_f".format(i), "write")),
                    duc.p.eq(self.decoder.get("duc{}_p".format(i), "write")),
                ),
            ]
            mux = self.decoder.get("duc_cfg", "write")[2*(i + 2):2*(i + 3)]
            for j, (ji, jo) in enumerate(zip(duc.i, duc.o)):
                self.comb += [
                    ji.eq(self.decoder.zoh.sample[i]),
                ]
                self.sync += [
                    If(mux == 0,
                        self.data.data[2*j][i].eq(jo.i),
                        self.data.data[2*j + 1][i].eq(jo.q),
                    )
                ]

            self.sync += [
                If(mux == 1,
                    Cat([d[i] for d in self.data.data]).eq(Cat(
                        self.decoder.get("dac{}_test".format(i), "write"),
                        self.decoder.get("dac{}_test".format(i), "write"))),
                )
            ]
        self.comb += [
            self.decoder.get("dac0_data", "read").eq(Cat([
                d[0] for d in self.data.data])),
            self.decoder.get("dac1_data", "read").eq(Cat([
                d[1] for d in self.data.data])),
        ]

        self.comb += [
            Cat([platform.request("test_point", i) for i in range(6)]).eq(Cat(
                #self.link.phy.clk,
                #ClockSignal(),
                #ResetSignal(),
                #self.link.slip.bitslip,
                #self.link.unframe.data[0],
                self.link.unframe.data[0],
                self.link.unframe.data[1],
                self.link.unframe.clk_stb,
                self.link.unframe.marker_stb,
                self.link.unframe.end_of_frame,
                #self.link.checker.frame_stb,
                #self.data.data_sync
            )) 
        ]


if __name__ == "__main__":
    from platform import Platform
    platform = Platform(load=True)
    test = Phaser(platform)
    platform.build(test, build_name="phaser")

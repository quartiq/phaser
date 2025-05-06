from migen import *
from misoc.cores.spi2 import SPIMachine, SPIInterface
from misoc.cores.duc import PhasedDUC

from crg import CRG
from link import Link
from decode import Decode, Register
from dac_data import DacData
from adc import Adc, AdcParams
from iir import Iir, Dsp

SERVO_PROFILES = 4  # number iir coefficient profiles per servo channel
SERVO_CHANNELS = 2  # number servochannels


class PWM(Module):
    """Pulse width modulation"""

    def __init__(self, pin, width=10):
        cnt = Signal(width, reset_less=True)
        self.duty = Signal.like(cnt)
        self.sync += [
            cnt.eq(cnt + 1),
            If(
                cnt == 0,
                pin.eq(1),
            ),
            If(
                cnt == self.duty,
                pin.eq(0),
            ),
        ]


class Phaser(Module):
    def __init__(self, platform):
        eem = platform.request("eem", 0)
        self.submodules.link = Link(eem)
        # Set up the CRG to clock everything from the link clock
        # This avoids CDCs and latency variation. All latency variation is
        # buffered by the DAC EB and compensated for by its reset mechanism
        # through ISTR (generated here from data clock) and OSTR (generated
        # w.r.t DAC clk by PLL at PFD frequency). Deterministic initial
        # conditions are set during initialization in terms
        # of optimal DAC EB output reset address (fifo_offset).
        platform.add_period_constraint(eem.data0_p, 4.0 * 8)
        self.submodules.crg = CRG(platform, link=self.link.phy.clk)
        # Don't bother meeting s/h for the clk iserdes. We align it.
        platform.add_false_path_constraint(eem.data0_p, self.crg.cd_sys2.clk)
        self.submodules.decoder = Decode(
            b_sample=14, n_channel=2, n_mux=8, t_frame=8 * 10
        )
        self.comb += [
            self.decoder.frame.eq(self.link.checker.frame),
            self.decoder.stb.eq(self.link.checker.frame_stb),
            # Send the 8 bit response early (msb aligned) and slowly (/8)
            # This gives 2 miso bits max rtt latency
            Cat(self.link.checker.response[2 * 8 :]).eq(
                Cat([Replicate(d, 8) for d in self.decoder.response])
            ),
        ]

        phaser_registers = [
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
            # dac data interface sync delay (for sync-dac_clk alignment and
            # n-div/pll/ostr fifo output synchronization)
            ("sync_dly", Register(width=3)),
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
            (
                "dac0_data",
                Register(write=False),
                Register(write=False),
                Register(write=False),
                Register(write=False),
            ),
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
            (
                "dac1_data",
                Register(write=False),
                Register(write=False),
                Register(write=False),
                Register(write=False),
            ),
            # dac test data for duc_cfg:data_select == 1
            ("dac1_test", Register(), Register(), Register(), Register()),
            (0x30,),
            # (ch0_profile[2], en0)
            ("servo0_cfg", Register()),
            # (ch1_profile[2], en1)
            ("servo1_cfg", Register()),
        ]

        # add servo data registers
        for i in range(SERVO_CHANNELS):
            for j in range(SERVO_PROFILES):
                for k in range(4):  # 3 coefficients + offset
                    phaser_registers.append(
                        (
                            f"ch{i}_profile{j}_data{k}",
                            Register(read=False),
                            Register(read=False),
                        )
                    )

        self.decoder.map_registers(phaser_registers)

        dac_ctrl = platform.request("dac_ctrl")
        trf_ctrl = [platform.request("trf_ctrl") for _ in range(2)]
        att_rstn = [platform.request("att_rstn") for _ in range(2)]
        adc_ctrl = platform.request("adc_ctrl")
        self.comb += [
            # Sinara.boards.index("Phaser") == 19
            self.decoder.get("board_id", "read").eq(19),
            self.decoder.get("hw_rev", "read").eq(
                Cat(platform.request("hw_rev"), platform.request("hw_variant"))
            ),
            self.decoder.get("gw_rev", "read").eq(0x01),
            Cat([platform.request("user_led", i) for i in range(6)]).eq(
                self.decoder.get("led", "write")
            ),
            Cat(
                platform.request("clk_sel"),
                dac_ctrl.resetb,
                dac_ctrl.sleep,
                dac_ctrl.txena,
                trf_ctrl[0].ps,
                trf_ctrl[1].ps,
                att_rstn[0],
                att_rstn[1],
            ).eq(self.decoder.get("cfg", "write")),
            Cat(adc_ctrl.gain0, adc_ctrl.gain1).eq(
                self.decoder.get("adc_cfg", "write")
            ),
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
            self.decoder.get("sta", "read").eq(
                Cat(
                    dac_ctrl.alarm,
                    trf_ctrl[0].ld,
                    trf_ctrl[1].ld,
                    adc_ctrl.term_stat,
                    self.spi.idle,
                )
            ),
            self.spi.load.eq(self.decoder.registers["spi_datw"][0].bus.we),
            self.spi.reg.pdo.eq(self.decoder.registers["spi_datw"][0].bus.dat_w),
            # self.spi.readable, self.spi.writable, self.spi.idle,
            self.spiint.cs.eq(self.decoder.get("spi_sel", "write")),
            self.spiint.cs_polarity.eq(0),  # all active low
            Cat(self.spi.cg.div[3:], self.spi.length).eq(
                self.decoder.get("spi_divlen", "write")
            ),
            Cat(
                self.spiint.offline,
                self.spi.end,
                self.spi.clk_phase,
                self.spiint.clk_polarity,
                self.spiint.half_duplex,
                self.spi.reg.lsb_first,
            ).eq(self.decoder.get("spi_cfg", "write")),
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

        # 32 ns t_cnvh, 12 ns t_conv/t_DCNVSCKL, 192 ns data transfer, 24 ns t_rtt/tDSCKLCNVH
        # Note that there is one extra cycle (4 ns) at the end of a transaction.
        # Total: 264 ns -> 3.788 MSps
        adc_parameters = AdcParams(
            width=16, channels=2, lanes=2, t_cnvh=8, t_conv=3, t_rtt=6
        )

        self.submodules.adc = adc = Adc(platform.request("adc"), adc_parameters)
        self.comb += adc.start.eq(1)

        # potential IIR improvements:
        # - Use a0=-1: invert y0 before or after clipping and flip the other coefficient signs
        # - a1 = (1 - epsilon) and pass epsilon as a 16 bit. Then use wider a1 in computation.
        # - unsigned output to gain the sign bit for data

        # log2_a0 = 14 bit for an effective fixedpoint a0 of 0.5
        self.submodules.iir = iir = Iir(
            w_coeff=16,
            w_data=16,
            log2_a0=14,
            n_profiles=SERVO_PROFILES,
            n_channels=SERVO_CHANNELS,
        )
        self.comb += [
            [inp.eq(data) for inp, data in zip(iir.inp, adc.data)],
            iir.stb_in.eq(adc.done),
        ]

        # connect iir to servo data registers
        for i in range(SERVO_CHANNELS):
            for j in range(SERVO_PROFILES):
                for k in range(3):  # 3 coefficients
                    self.comb += iir.coeff[k][j][i].eq(
                        self.decoder.get(f"ch{i}_profile{j}_data{k}", "write")
                    )
                self.comb += iir.offset[j][i].eq(
                    self.decoder.get(f"ch{i}_profile{j}_data3", "write")
                )

        # connect hold and profile select so that they update after a filter update is done
        self.sync += [
            If(
                iir.stb_out,
                # bit 0 is the ch enable bit, bit 1 the hold bit
                iir.ch_profile[0].eq(self.decoder.get(f"servo0_cfg", "write")[2:]),
                iir.ch_profile[1].eq(self.decoder.get(f"servo1_cfg", "write")[2:]),
                iir.hold[0].eq(self.decoder.get(f"servo0_cfg", "write")[1]),
                iir.hold[1].eq(self.decoder.get(f"servo1_cfg", "write")[1]),
            )
        ]

        self.submodules.dac = DacData(platform.request("dac_data"))
        self.comb += [
            # sync istr counter every frame
            # this is correct since dac samples per frame is 8*20 and
            # thus divisible by the EB depth of 8.
            self.dac.data_sync.eq(self.decoder.stb),
            self.dac.sync_dly.eq(self.decoder.get("sync_dly", "write")),
        ]
        for ch in range(2):
            duc = PhasedDUC(n=2, pwidth=19, fwidth=32, zl=10)
            self.submodules += duc
            cfg = self.decoder.get("duc{}_cfg".format(ch), "write")
            servo_enable = self.decoder.get("servo{}_cfg".format(ch), "write")[0]
            self.sync += [
                # keep accu cleared
                duc.clr.eq(cfg[0]),
                If(
                    self.decoder.registers["duc_stb"][0].bus.we,
                    # clear accu once
                    If(
                        cfg[1],
                        duc.clr.eq(1),
                    ),
                    duc.f.eq(self.decoder.get("duc{}_f".format(ch), "write")),
                    # msb align to 19 bit duc.p
                    duc.p[3:].eq(self.decoder.get("duc{}_p".format(ch), "write")),
                ),
            ]
            for t, (ti, to) in enumerate(zip(duc.i, duc.o)):
                servo_dsp_i = Dsp()
                servo_dsp_q = Dsp()
                self.submodules += [servo_dsp_i, servo_dsp_q]
                self.comb += [
                    ti.i.eq(self.decoder.data[t][ch].i),
                    ti.q.eq(self.decoder.data[t][ch].q),
                    servo_dsp_i.c.eq(
                        (1 << len(self.dac.data[2 * t][ch]) - 2) - 1
                    ),  # rounding offset
                    servo_dsp_q.c.eq((1 << len(self.dac.data[2 * t][ch]) - 2) - 1),
                ]
                self.sync += [
                    If(
                        cfg[2:4] == 0,  # ducx_cfg_sel
                        self.dac.data[2 * t][ch].eq(to.i),
                        self.dac.data[2 * t + 1][ch].eq(to.q),
                    ),
                    servo_dsp_i.a.eq(to.i),
                    servo_dsp_q.a.eq(to.q),
                    servo_dsp_i.b.eq(iir.outp[ch]),
                    servo_dsp_q.b.eq(iir.outp[ch]),
                    If(
                        servo_enable,
                        self.dac.data[2 * t][ch].eq(
                            servo_dsp_i.p >> len(self.dac.data[2 * t][ch]) - 1
                        ),
                        self.dac.data[2 * t + 1][ch].eq(
                            servo_dsp_q.p >> len(self.dac.data[2 * t][ch]) - 1
                        ),
                    ),
                ]

            self.sync += [
                If(
                    cfg[2:4] == 1,  # ducx_cfg_sel
                    # i is lsb, q is msb
                    # repeat the test data to fill the oserdes
                    Cat([d[ch] for d in self.dac.data]).eq(
                        Replicate(self.decoder.get("dac{}_test".format(ch), "write"), 2)
                    ),
                ),
            ]
            self.comb += [
                # even sample just before the oserdes
                self.decoder.get("dac{}_data".format(ch), "read").eq(
                    Cat(d[ch] for d in self.dac.data)
                ),
            ]

        # use liberally for debugging
        self.comb += [
            Cat([platform.request("test_point", i) for i in range(6)]).eq(
                Cat(
                    ClockSignal("clk125"),
                    ClockSignal("link"),
                    # ClockSignal(),
                    # ResetSignal(),
                    # # self.link.slip.bitslip,
                    # # self.link.unframe.data[0],
                    # # self.link.unframe.data[1],
                    # # self.link.unframe.clk_stb,
                    # # self.link.unframe.marker_stb,
                    # # self.link.unframe.end_of_frame,
                    # self.link.checker.frame_stb,
                    # # self.decoder.bus.bus.we,
                    # # self.decoder.bus.bus.re,
                    # # self.decoder.bus.bus.adr[0],
                    # self.link.checker.miso,
                    # # self.dac.data_sync,
                    # self.dac.istr,
                    # dac_ctrl.alarm,
                    ClockSignal("ret"),
                    adc.cnvn,
                    adc.sdo[0],
                    adc.data[1][0],
                )
            )
        ]


if __name__ == "__main__":
    from migen.build.platforms.sinara.phaser import Platform

    platform = Platform()
    # platform.toolchain.additional_commands.extend([
    #     "set argv phaser.bit",
    #     "source ../load.tcl",
    # ])
    top = Phaser(platform)
    platform.build(top, build_name="phaser")

from migen import *
from misoc.cores.spi2 import SPIMachine, SPIInterface
from misoc.cores.duc import PhasedDUC

from crg import CRG
from link_sim import Link  # sim import
from decode_sim import Decode, Register  # sim import
from dac_data import DacData
from stft_pulsegen.pulsegen import Pulsegen

class Phaser(Module):
    def __init__(self):
        self.submodules.link = Link()
        # Set up the CRG to clock everything from the link clock
        # This avoids CDCs and latency variation. All latency variation is
        # buffered by the DAC EB and compensated for by its reset mechanism
        # through ISTR (generated here from data clock) and OSTR (generated
        # w.r.t DAC clk by PLL at PFD frequency). Deterministic initial
        # conditions are set during initialization in terms
        # of optimal DAC EB output reset address (fifo_offset).
        

        self.submodules.decoder = Decode(
            b_sample=14, n_channel=2, n_mux=8, t_frame=8*10)
        self.comb += [
            self.decoder.frame.eq(self.link.checker.frame),
            self.decoder.stb.eq(self.link.checker.frame_stb),
            # Send the 8 bit response early (msb aligned) and slowly (/8)
            # This gives 2 miso bits max rtt latency
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
            # cfg[2:4] = 3  pulsegen mode
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

            # STFT regs
            ("pulse_trigger", Register()),  # triggers immediate pulse emission
            ("pulse_settings", Register()),  # general pulse settings like immediate pulse emission
            ("fft_load", Register()),  # enables fft loading. data samples will be written into fft mem
            ("fft_size", Register()),  # (virtually) sets the fft size
            ("fft_shiftmask", Register(), Register()),  # fft stage shifting schedule
            ("repeater", Register(), Register()),  # number fft repeats
            ("fft_start", Register()),  # starts fft computation
            ("interpolation_rate", Register(), Register()),  # set interpolation rate

            ("fft_busy", Register()),  # fft core in computation
            ("pulsegen_busy", Register()),  # pulsegen in pulse ejection
        ])



        # stft pulsegen
        self.submodules.pulsegen = pulsegen = Pulsegen(self.decoder)


    def sim(self):
        for i in range(500):
            yield

            if i == 10:
                yield self.link.checker.frame.eq(1 | 50 << 1 | 1 << 8 | 1 << 16)  # assert fft load
                yield self.link.checker.frame_stb.eq(1)  # update fft_load reg on first frame
                yield
                yield self.link.checker.frame_stb.eq(0)
                yield self.link.checker.frame.eq(1 | 50<<1 | 1<<16 | 1<<20 | 2**15<<(20+64) | 2**15<<(20+96))
                # write some data to first and second coef and de-assert fft_load
                yield
                yield self.link.checker.frame_stb.eq(1)  # second frame contains data
                yield
                yield self.link.checker.frame_stb.eq(0)
                yield self.link.checker.frame.eq(1 | 56 << 1 | 1 << 8 | 1 << 16)  # fft start
                yield self.link.checker.frame_stb.eq(1)
                yield
                yield self.link.checker.frame_stb.eq(0)

            if i == 20:
                yield self.link.checker.frame.eq(1 | 49 << 1 | 1 << 8 | 1 << 16)  # set pulse settings
                yield self.link.checker.frame_stb.eq(1)
                yield
                yield self.link.checker.frame_stb.eq(0)
                yield
                yield self.link.checker.frame.eq(1 | 55<<1 | 3 << 8 | 1 << 16)  # set nr repeats
                yield self.link.checker.frame_stb.eq(1)
                yield
                yield self.link.checker.frame_stb.eq(0)
                yield
                yield self.link.checker.frame.eq(1 | 48<<1 | 1 << 8 | 1 << 16)  # emit pulse as soon as fft is done
                yield self.link.checker.frame_stb.eq(1)
                yield
                yield self.link.checker.frame_stb.eq(0)




if __name__ == "__main__":
    top = Phaser()
    run_simulation(top, top.sim(), vcd_name="phaser.vcd")

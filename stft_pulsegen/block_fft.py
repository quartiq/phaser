# SingularitySurfer 2020


import numpy as np
from migen import *
from functools import reduce
from operator import and_


class Fft(Module):
    """Migen FFT generator

        Radix-2 division in time (DIT) block-FFT.
        Complex datasamples are first loaded into the memory, an FFT is performed on the data and
        computed FFT samples can then be read out. Imag and real part are represented concatenated.
        One pipelined butterfly computation core iterates over the data and computes one
        set of two new complex samples each clockcycle.
        The complete FFT therefore takes ((N/2)*log2(N))+PIPE_DELAY clockcycles.

        Butterfly core:
        The butterfly core contains the pipelined computation datapath, the twiddle memory,
        twiddle decoder and twiddle address calculator. Complex multiplication is implemented
        3 DSPs and adders with rounding and scaling at the end. The core is fully pipelined,
        ingesting two inputs and emitting two outputs at every clockcycle. The full pipeline
        length with registered ram output is 8 cycles. Writeback happens in the same cycle as
        the last computation.

        Twiddle Factors:
        The Twiddle factors are basically just points on the unit circle. Due to symmetries
        a lot of the points can be generated from only 1/4th of the full circle. The twiddle
        decoder multiplexes the saved data to the right position for the requested twiddle factor.

        Memory multiplexing:
        There are 3 banks of data-ram in total. ram1 always gets read and written in order,
        while ram2a and ram2b contain data in a shuffled order so that the butterfly core can
        always read its two inputs from different memory banks. Due to the pipeline delay
        in the computation, the second ram needs to be double buffered so that data of the
        current fft stage doesn't get overwritten (in ram1 the data overwritten is always
        expendable).
        There are better but more complicated memory schemes that don't require double buffering.

        Scaling:
        Scaling is provided via a scaling bitmask with length nr. stages. If the bitmask is all
        zeros the output of every bfl stage will be scaled by one resulting in the default 1/N factor.
        If the bitmask is 1 at the current stage the output will NOT be scaled and therefore
        grow by one bit. The overall fft is therefore scaled by 2^(zeros in bitmask).
        Bitgrowth is usually preferred at the first stages so the errors dont get multiplied
        by later stages. This can lead to overflow if the coeffs are not well understood!


        Parameters
        ----------
        n : FFT size
        ifft : forward or inverse FFT
        width_i : input width
        width_o : output width
        width_int : internal computation and memory width
        width_wram : twiddle memory width
        input_bitreversed : natural or bit-reversed input
    """

    def __init__(self, n=32, ifft=False, width_i=16, width_o=16, width_int=16,
                 width_wram=16, input_bitreversed=False):
        # Parameters
        self.n = n
        self.width_int = width_int
        self.width_i = width_i
        self.width_o = width_o
        self.width_wram = width_wram
        self.ifft = ifft
        m = np.log2(n)
        assert m % 1 == 0, "input vector length needs to be power of two long"
        self.log2n = int(m)

        ### IO signals
        self.x_in = Signal((self.width_i * 2, True))  # write data
        self.x_in_we = Signal()  # write enable
        self.x_in_adr = Signal(self.log2n)  # write address
        self.x_out = Signal((self.width_o * 2, True))  # read data
        self.x_out_adr = Signal(self.log2n)  # read address
        self.scaling = Signal(self.log2n)  # scaling mask
        self.start = Signal()  # input start signal
        self.busy = Signal()  # busy indicator
        self.done = Signal()  # output done signal
        ###

        # internal Signals
        ar = Signal((self.width_int, True))
        ai = Signal((self.width_int, True))
        br = Signal((self.width_int, True))
        bi = Signal((self.width_int, True))
        self.stage = Signal(int(np.ceil(np.log2(self.log2n))) + 1)  # global stage counter
        self.en = Signal()  # global bfl computation enable Signal
        self.scaling_reg = Signal(self.log2n)  # registered scaling value
        s = Signal()  # butterfly computations output scaling signal

        # Instantiate Butterfly
        cr, ci, dr, di = self._bfl_core(ar, ai, br, bi, s)

        # Data Memories
        xram1 = Memory(width_int * 2, int(n / 2), name="data1")
        xram2a = Memory(width_int * 2, int(n / 2), name="data2a")
        xram2b = Memory(width_int * 2, int(n / 2), name="data2b")
        xram1_port1 = xram1.get_port(write_capable=True, mode=WRITE_FIRST)
        xram1_port2 = xram1.get_port(write_capable=True)
        xram2a_port1 = xram2a.get_port(write_capable=True, mode=WRITE_FIRST)
        xram2a_port2 = xram2a.get_port(write_capable=True)
        xram2b_port1 = xram2b.get_port(write_capable=True, mode=WRITE_FIRST)
        xram2b_port2 = xram2b.get_port(write_capable=True)
        dat_r = Signal(width_int * 2)
        self.specials += xram1, xram1_port1, xram1_port2, xram2a, \
                         xram2b, xram2a_port1, xram2a_port2, xram2b_port1, xram2b_port2

        # Memory Wiring
        a_mux_l, c_mux, a_x2_mux_l, c_x2_mux, x1p1_adr, x1p2_adr, x2p1_adr, x2p2_adr, bfl_we, stage_w_n \
            = self._data_scheduler()

        inp_ram_adr = Signal(self.log2n)  # physical ram adress
        last_bit_xout_adr_l = Signal()  # one clock delayed for correct output routing after ram access

        self.comb += [  # fetching/loading ports
            xram1_port1.adr.eq(Mux(self.busy, x1p1_adr, inp_ram_adr[1:])),
            xram2a_port1.adr.eq(Mux(self.busy, x2p1_adr, inp_ram_adr[1:])),
            xram2b_port1.adr.eq(Mux(self.busy, x2p1_adr, inp_ram_adr[1:])),
            xram1_port1.dat_w.eq(self.x_in),
            xram2a_port1.dat_w.eq(self.x_in),
            xram2b_port1.dat_w.eq(self.x_in),
            xram1_port1.we.eq(~self.busy & self.x_in_we & ~inp_ram_adr[0]),
            # use LSB of address to switch between rams when loading data
            xram2a_port1.we.eq(~self.busy & self.x_in_we & inp_ram_adr[0]),
            xram2b_port1.we.eq(~self.busy & self.x_in_we & inp_ram_adr[0]),
            ar.eq(Mux(a_mux_l == 0, xram1_port1.dat_r[:self.width_int], dat_r[:self.width_int])),
            ai.eq(Mux(a_mux_l == 0, xram1_port1.dat_r[self.width_int:], dat_r[self.width_int:])),
            br.eq(Mux(a_mux_l, xram1_port1.dat_r[:self.width_int], dat_r[:self.width_int])),
            bi.eq(Mux(a_mux_l, xram1_port1.dat_r[self.width_int:], dat_r[self.width_int:])),
            dat_r.eq(Mux(a_x2_mux_l, xram2a_port1.dat_r, xram2b_port1.dat_r)),
        ]
        self.comb += [  # writeback/retrieval ports
            xram1_port2.adr.eq(Mux(self.busy, x1p2_adr, self.x_out_adr[:-1])),
            xram2a_port2.adr.eq(Mux(self.busy, x2p2_adr, self.x_out_adr[:-1])),
            xram2b_port2.adr.eq(Mux(self.busy, x2p2_adr, self.x_out_adr[:-1])),
            self.x_out.eq(
                Mux(last_bit_xout_adr_l == 0, xram1_port2.dat_r,  # first half of data is in ram1, second in ram2
                    Mux(c_x2_mux, xram2a_port2.dat_r, xram2b_port2.dat_r))),  # fetch from last used ram2
            xram1_port2.we.eq(self.busy & bfl_we),
            xram2a_port2.we.eq(self.busy & (bfl_we & c_x2_mux)),
            xram2b_port2.we.eq(self.busy & (bfl_we & (~c_x2_mux))),
            xram1_port2.dat_w.eq(Cat(Mux(c_mux == 0, cr, dr), Mux(c_mux == 0, ci, di))),
            xram2a_port2.dat_w.eq(Cat(Mux(c_mux, cr, dr), Mux(c_mux, ci, di))),
            xram2b_port2.dat_w.eq(Cat(Mux(c_mux, cr, dr), Mux(c_mux, ci, di))),
        ]
        self.sync += [
            last_bit_xout_adr_l.eq(self.x_out_adr[-1])  # delay by one clk
        ]

        # IO logic
        if input_bitreversed:
            self.comb += [
                inp_ram_adr.eq(self.x_in_adr),  # no bitreversing, just in order
            ]
        else:
            self.comb += [
                inp_ram_adr.eq(self.x_in_adr[::-1]),  # reverse bits
            ]

        # scaling logic
        self.comb += [
            s.eq(~Array(self.scaling_reg)[stage_w_n]),  # scaling signal is needed one clk before stage transition
        ]

    def _data_scheduler(self):
        """data ram address and ram multiplexer scheduler."""
        pos_r = Signal(self.log2n - 1, reset=0)  # read position reg
        pos_w = Signal(self.log2n - 1, reset=0)  # pipeline delay delayed couter
        stage_w = Signal(int(np.ceil(np.log2(self.log2n))) + 1,
                         reset=0)  # write stage position; resets to -1 at fft start
        stage_w_n = Signal(int(np.ceil(np.log2(self.log2n))) + 1,
                           reset=0)  # write stage position at NEXT clockcycle; resets to -1 at fft start
        a_mux = Signal()  # a ram muxing signal
        c_mux = Signal()  # c ram muxing signal
        a_mux_l = Signal()  # (last) 1 clk delayed mux; needed to route data at ram output one clk after addr was set
        a_x2_mux = Signal()  # a muxing signal for double buffered x2 ram
        c_x2_mux = Signal()  # c muxing signal for double buffered x2 ram
        a_x2_mux_l = Signal()  # (last) 1 clk delayed a x2 muxing signal
        bfl_we = Signal()  # ram write enable
        posbit_r = Signal()  # one bit of read position counter
        posbit_w = Signal()  # one bit or write position counter
        laststart = Signal()  # start signal one clk cycle ago
        x1p1_adr = Signal(self.log2n - 1)
        x1p2_adr = Signal(self.log2n - 1)
        x2p1_adr = Signal(self.log2n - 1)
        x2p2_adr = Signal(self.log2n - 1)

        self.sync += [
            # start/stop logic
            laststart.eq(self.start),
            If((self.start & (~laststart) & ~self.busy),  # if start signal was set
               self.busy.eq(1),
               self.done.eq(0),
               self.stage.eq(0),
               stage_w.eq(-1),
               stage_w_n.eq(-1),
               pos_r.eq(0),
               self.scaling_reg.eq(self.scaling),
               # starting at scaling_reg stage, the bfl outputs are not scaled any more.
               ),
            If(reduce(and_, pos_w) & (stage_w == self.log2n - 1),  # if at last write
               bfl_we.eq(0),
               self.busy.eq(0),
               self.done.eq(1),
               ),

            # position and staging
            If(self.en & self.busy, pos_r.eq(pos_r + 1)),  # count only if enabled; overflows at stage transition
            If(reduce(and_, pos_r), self.stage.eq(self.stage + 1)),
            If(reduce(and_, pos_w) & ~(stage_w == self.log2n - 1), stage_w.eq(stage_w + 1)),
            If(pos_w == (int(self.n / 2) - 2), stage_w_n.eq(stage_w_n + 1)),  # grr, this is ugly
            # dont count up write pos at ultimate stage so c_x2_mux is still in the right position
            If(reduce(and_, pos_w) & reduce(and_, stage_w) & (self.busy == 1), bfl_we.eq(1)),
            # enable write on next (stage_w==0) cycle
            a_mux_l.eq(a_mux),  # a_mux is needed one cycle later to route data output of ram
            a_x2_mux_l.eq(a_x2_mux)
        ]

        self.comb += posbit_r.eq(Array(pos_r)[self.stage - 1])  # Mux for read position bits
        self.comb += [posbit_w.eq(Array(pos_w)[stage_w]),  # Mux for write position bits
                      If(stage_w >= self.log2n - 1, posbit_w.eq(0))]

        self.comb += [
            # fetching logic
            a_x2_mux.eq(self.stage[0]),  # use last bit of stage to toggle between x2 mems
            a_mux.eq(Mux(self.stage == 0, 0, posbit_r)),
            # input multiplexer needs to switch every self.stage cycles (so never in the 0th stage)
            x1p1_adr.eq(pos_r),  # ram 1 is just always sorted
            x2p1_adr.eq((Cat(0, pos_r) ^ (1 << self.stage)) >> 1),
            # flip bit at self.stage position to shuffle ram 2;
            # first append 0 at LSB and then shift out to effectively make self.stage-1.

            # writeback logic
            pos_w.eq(pos_r - self.PIPE_DELAY),  # writeback needs to be delayed due to pipelining
            c_x2_mux.eq(~stage_w[0]),  # use last bit of stage to toggle between x2 mems
            c_mux.eq(posbit_w),  # toggle c mux at stage bit of write position
            x1p2_adr.eq(pos_w),  # ram 1 is just always sorted
            x2p2_adr.eq(pos_w)  # ram 2 is also read in order
        ]
        return a_mux_l, c_mux, a_x2_mux_l, c_x2_mux, x1p1_adr, x1p2_adr, x2p1_adr, x2p2_adr, bfl_we, stage_w_n

    def _bfl_core(self, ar, ai, br, bi, s):
        """full butterfly core with computation pipeline, twiddle rom and twiddle address calculator."""
        w_idx = self._twiddle_addr_calc()
        wr, wi = self._twiddle_mem_gen(w_idx)
        return self._bfl_pipe3_dsp_opt(ar, ai, br, bi, wr, wi, s)

    def _bfl_pipe3_dsp_opt(self, ar, ai, br, bi, wr, wi, s):
        """Butterfly computation pipe.
        Optimized for pipelined dsp blocks. Adapted from misoc duc ComplexMultiplier.
        """
        self.PIPE_DELAY = 8
        bias = (1 << self.w_p - 1) - 1
        cr = Signal((self.width_int, True), reset_less=True)
        ci = Signal((self.width_int, True), reset_less=True)
        dr = Signal((self.width_int, True), reset_less=True)
        di = Signal((self.width_int, True), reset_less=True)
        ar_reg = [Signal((self.width_int, True), reset_less=True) for _ in range(6)]
        ai_reg = [Signal((self.width_int, True), reset_less=True) for _ in range(6)]
        br_reg = [Signal((self.width_int, True), reset_less=True) for _ in range(4)]
        bi_reg = [Signal((self.width_int, True), reset_less=True) for _ in range(4)]
        wr_reg = [Signal((self.width_int, True), reset_less=True) for _ in range(3)]
        wi_reg = [Signal((self.width_int, True), reset_less=True) for _ in range(3)]
        bd = Signal((self.width_int + 1, True), reset_less=True)
        ws = Signal((self.width_int + 1, True), reset_less=True)
        wd = Signal((self.width_int + 1, True), reset_less=True)
        m = [Signal((self.width_int * 2 + 1, True), reset_less=True)
             for _ in range(8)]
        self.sync += [
            # 0th stage: ram access
            Cat(ar_reg).eq(Cat(ar, ar_reg)),  # 1
            Cat(ai_reg).eq(Cat(ai, ai_reg)),  # 1
            Cat(br_reg).eq(Cat(br, br_reg)),  # 1
            Cat(bi_reg).eq(Cat(bi, bi_reg)),  # 1
            Cat(wr_reg).eq(Cat(wr, wr_reg)),  # 1
            Cat(wi_reg).eq(Cat(wi, wi_reg)),  # 1
            bd.eq(br_reg[0] + bi_reg[0]),  # 2
            m[0].eq(bd * wr_reg[1]),  # 3
            m[1].eq(m[0] + bias),  # 4
            ws.eq(wr_reg[2] + wi_reg[2]),  # 4
            wd.eq(wr_reg[2] - wi_reg[2]),  # 4
            m[2].eq(ws * bi_reg[3]),  # 5
            m[3].eq(wd * br_reg[3]),  # 5
            m[4].eq(m[1]),  # 5
            m[5].eq(m[1]),  # 5
            m[6].eq(m[4] - m[2]),  # 6
            m[7].eq(m[5] - m[3]),  # 6
            cr.eq((ar_reg[5] + m[6][self.w_p:]) >> s),  # 7
            ci.eq((ai_reg[5] + m[7][self.w_p:]) >> s),  # 7
            dr.eq((ar_reg[5] - m[6][self.w_p:]) >> s),  # 7
            di.eq((ai_reg[5] - m[7][self.w_p:]) >> s),  # 7
        ]
        return cr, ci, dr, di

    def _twiddle_mem_gen(self, w_idx):
        """generates twiddle rom and logic for assembling the twiddles from one quarter circle"""
        pos = np.linspace(0, np.pi / 2, int(self.n / 4), False)
        self.w_p = self.width_wram - 2  # Fixed point position of twiddles. One bit is sign and one is nonfractional (ie 1 at the 0th twiddle)
        twiddles = [(int(_.real) | int(_.imag) << self.width_wram) & (1 << self.width_wram*2)-1
                    for _ in np.round((1 << (self.width_wram - 2)) * np.exp(-1j * pos))]
        wram = Memory(self.width_wram * 2, int(self.n / 4), init=twiddles, name="twiddle")
        wram_port = wram.get_port()
        self.specials += wram, wram_port
        wr = Signal((self.width_wram, True))
        wi = Signal((self.width_wram, True))
        wr_ram = Signal((self.width_wram, True))
        wi_ram = Signal((self.width_wram, True))
        w_idx_l = Signal()  # last upper index bits
        self.comb += [
            wram_port.adr.eq(w_idx[:-1]),
            wr_ram.eq(wram_port.dat_r[:self.width_wram]),  # get twiddle real
            wi_ram.eq(wram_port.dat_r[self.width_wram:]),  # get twiddle imag
        ]
        if self.ifft:
            self.comb += [
                wr.eq(Mux(w_idx_l, wi_ram, wr_ram)),
                wi.eq(Mux(w_idx_l, wr_ram, -wi_ram))
            ]
        else:
            self.comb += [
                wr.eq(Mux(w_idx_l, wi_ram, wr_ram)),
                wi.eq(Mux(w_idx_l, -wr_ram, wi_ram))
            ]
        self.sync += w_idx_l.eq(w_idx[-1])
        return wr, wi

    def _twiddle_addr_calc(self):
        """ calculates address for twiddle rotator """
        w_idx = Signal(self.log2n - 1, reset=0)
        step = Signal(self.log2n)  # make one bigger than w_idx to have overflow every step in 0th stage
        for i in range(self.log2n):
            self.comb += If(self.stage == i, step.eq(1 << (self.log2n - i - 1)))
        self.sync += If(self.en, w_idx.eq(w_idx + step))
        return w_idx
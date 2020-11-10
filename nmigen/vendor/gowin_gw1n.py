from abc import abstractproperty

from nmigen.hdl import *
from nmigen.lib.cdc import ResetSynchronizer
from nmigen.build import *


__all__ = ["GowinGW1NPlatform"]


class GowinGW1NPlatform(TemplatedPlatform):
    """
    Official Gowin toolchain
    ------------------------

    Required tools:
        * ``GowinSynthesis`` (optional)
        * `` yosys``
        * ``gw_sh``

    The environment is populated by running the script specified in the environment variable
    ``NMIGEN_ENV_Gowin``, if present.

    Available overrides:
    **TODO**

    Build products:
        * ``{{name}}.vg``: synthesized RTL.
        * ``{{name}}.log``: synthesis log.
        * ``imp/pnr/{{name}}.log``: PnR log.
        * ``imp/pnr/{{name}}.rpt.txt``: PnR report.
        * ``imp/pnr/{{name}}.fs``: ASCII bitstream.

    Apicula toolchain
    -----------------
    TODO

    """

    toolchain = None # selected when creating platform

    device  = abstractproperty()
    package = abstractproperty()

    # Gowin templates

    _gowin_required_tools = [
        "GowinSynthesis",
        "gw_sh",
        "yosys"
    ]
    _gowin_file_templates = {
        **TemplatedPlatform.build_script_templates,
        "{{name}}.il": r"""
            # {{autogenerated}}
            {{emit_rtlil()}}
        """,
        "{{name}}.debug.v": r"""
            /* {{autogenerated}} */
            {{emit_debug_verilog()}}
        """,
        "{{name}}.ys": r"""
            # {{autogenerated}}
            {% for file in platform.iter_files(".v") -%}
                read_verilog {{get_override("read_verilog_opts")|options}} {{file}}
            {% endfor %}
            {% for file in platform.iter_files(".sv") -%}
                read_verilog -sv {{get_override("read_verilog_opts")|options}} {{file}}
            {% endfor %}
            {% for file in platform.iter_files(".il") -%}
                read_ilang {{file}}
            {% endfor %}
            read_ilang {{name}}.il
            {{get_override("script_after_read")|default("# (script_after_read placeholder)")}}
            synth_gowin {{get_override("synth_opts")|options}} -top {{name}} -vout {{name}}_raw.vg

            # Workaround for PnR tool bug: IOBUF and TBUF require ports to be passed directly, not via wires.
            opt_clean -purge
            write_verilog -decimal -attr2comment -defparam -renameprefix gen {{name}}.vg

            {{get_override("script_after_synth")|default("# (script_after_synth placeholder)")}}
        """,
        # TODO: Make IO_TYPE variable
        "{{name}}.cst": r"""
            # {{autogenerated}}
            {% for port_name, pin_name, attrs in platform.iter_port_constraints_bits() -%}
                IO_LOC "{{port_name}}" {{pin_name}};
            {% endfor %}
            {% for port_name, pin_name, attrs in platform.iter_port_constraints_bits() -%}
                IO_PORT "{{port_name}}" IO_TYPE=LVCMOS33;
            {% endfor %}
        """,
        "{{name}}.sdc": r"""
            {% for net_signal, port_signal, frequency in platform.iter_clock_constraints() -%}
                create_clock -name {{net_signal|hierarchy(".")}} -period {{1000000000/frequency}} -waveform {0 {{500000000/frequency}}} [get_ports { {{port_signal.name}} }]
            {% endfor%}

        """,
        "run.tcl": r"""
            add_file -type cst {{name}}.cst
            add_file -type sdc {{name}}.sdc
            add_file -type netlist {{name}}.vg
            set_device -name {{platform.device}} {{platform.family}}-{{platform.voltage}}{{platform._device_suffix}}{{platform.package}}{{platform.speed}}
            set_option -gen_posp 1
            set_option -show_all_warn 1

            # TODO: The following gpios may be a bit dangerous to enable, depending on the board used.

            #set_option -use_jtag_as_gpio 1
            set_option -use_sspi_as_gpio 1
            set_option -use_mspi_as_gpio 1
            #set_option -use_ready_as_gpio 1
            #set_option -use_done_as_gpio 1
            #set_option -use_reconfign_as_gpio 1
            #set_option -use_mode_as_gpio 1

            run pnr
        """,
    }
    _gowin_command_templates = [
        # r"""
        # {{invoke_tool("GowinSynthesis")}}
        #     -i {{name}}.debug.v
        # """,

        r"""
        {{invoke_tool("yosys")}}
            {{quiet("-q")}}
            {{get_override("yosys_opts")|options}}
            -l {{name}}.rpt
            {{name}}.ys
        """,

        r"""
        {{invoke_tool("gw_sh")}}
            run.tcl
        """,

        # HACK: Move the artifact to the build directory
        r"""
        {{invoke_tool("bash")}}
            -c "
                cp -f impl/pnr/{{name}}.fs ./
            "
        """,
    ]

    # Common logic

    def __init__(self, *, toolchain="Gowin"):
        super().__init__()

        assert toolchain in ("Gowin")
        self.toolchain = toolchain

    @property
    def family(self):
        if self.device.startswith("GW1N"):
            return "GW1N"
        assert False

    @property
    def _device_suffix(self):
        return self.device.split("-")[1]

    @property
    def _toolchain_env_var(self):
        if self.toolchain == "Gowin":
            return f"NMIGEN_ENV_{self.toolchain}"
        assert False

    @property
    def required_tools(self):
        if self.toolchain == "Gowin":
            return self._gowin_required_tools
        assert False

    @property
    def file_templates(self):
        if self.toolchain == "Gowin":
            return self._gowin_file_templates
        assert False

    @property
    def command_templates(self):
        if self.toolchain == "Gowin":
            return self._gowin_command_templates
        assert False

    def create_missing_domain(self, name):
        if name == "sync" and self.default_clk is not None:
            m = Module()

            # TODO: Add internal oscillators

            # User-defined clock signal.
            clk_i = self.request(self.default_clk).i
            delay = int(15e-6 * self.default_clk_frequency)

            if self.default_rst is not None:
                rst_i = self.request(self.default_rst).i
            else:
                rst_i = Const(0)

            # Power-on-reset domain
            m.domains += ClockDomain("por", reset_less=True, local=True)
            timer = Signal(range(delay))
            ready = Signal()
            m.d.comb += ClockSignal("por").eq(clk_i)
            with m.If(timer == delay):
                m.d.por += ready.eq(1)
            with m.Else():
                m.d.por += timer.eq(timer + 1)

            # Primary domain
            m.domains += ClockDomain("sync")
            m.d.comb += ClockSignal("sync").eq(clk_i)
            if self.default_rst is not None:
                m.submodules.reset_sync = ResetSynchronizer(~ready | rst_i, domain="sync")
            else:
                m.d.comb += ResetSignal("sync").eq(~ready)

            return m

    def should_skip_port_component(self, port, attrs, component):
        # TODO: Review this later, might be needed for diff pairs?
        return False

    def _get_xdr_buffer(self, m, pin, *, i_invert=False, o_invert=False):
        # TODO: This is broken for xdr>0 and diff pairs

        def get_ireg(clk, d, q):
            for bit in range(len(q)):
                m.d[clk] += d[bit].eq(q[bit])

        def get_oreg(clk, d, q):
            for bit in range(len(q)):
                print(d[0], clk)
                m.d[clk] += d[bit].eq(q[bit])

        def get_ineg(z, invert):
            if invert:
                a = Signal.like(z, name_suffix="_n")
                m.d.comb += z.eq(~a)
                return a
            else:
                return z

        def get_oneg(a, invert):
            if invert:
                z = Signal.like(a, name_suffix="_n")
                m.d.comb += z.eq(~a)
                return z
            else:
                return a

        if "i" in pin.dir:
            if pin.xdr < 2:
                pin_i  = get_ineg(pin.i,  i_invert)
        if "o" in pin.dir:
            if pin.xdr < 2:
                pin_o  = get_oneg(pin.o,  o_invert)

        i = o = t = None
        if "i" in pin.dir:
            i = Signal(pin.width, name="{}_xdr_i".format(pin.name))
        if "o" in pin.dir:
            o = Signal(pin.width, name="{}_xdr_o".format(pin.name))
        if pin.dir in ("oe", "io"):
            t = Signal(1,         name="{}_xdr_t".format(pin.name))

        if pin.xdr == 0:
            if "i" in pin.dir:
                i = pin_i
            if "o" in pin.dir:
                o = pin_o
            if pin.dir in ("oe", "io"):
                t = ~pin.oe
        elif pin.xdr == 1:
            if "i" in pin.dir:
                get_ireg(pin.i_clk, i, pin_i)
            if "o" in pin.dir:
                get_oreg(pin.o_clk, pin_o, o)
            if pin.dir in ("oe", "io"):
                get_oreg(pin.o_clk, ~pin.oe, t)
        else:
            assert False

        return (i, o, t)

    def get_input(self, pin, port, attrs, invert):
        self._check_feature("single-ended input", pin, attrs,
                            valid_xdrs=(0, 1), valid_attrs=True)
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, i_invert=invert)

        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("IBUF",
                i_I=port.io[bit],
                o_O=i[bit]
            )
        return m

    def get_output(self, pin, port, attrs, invert):
        self._check_feature("single-ended output", pin, attrs,
                            valid_xdrs=(0, 1), valid_attrs=True)
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, o_invert=invert)

        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("OBUF",
                i_I=o[bit],
                o_O=port.io[bit]
            )
        return m

    def get_tristate(self, pin, port, attrs, invert):
        self._check_feature("single-ended tristate", pin, attrs,
                            valid_xdrs=(0, 1), valid_attrs=True)
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, o_invert=invert)
        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("TBUF",
                i_OEN=t,
                i_I=o[bit],
                o_O=port.io[bit]
            )
        return m

    def get_input_output(self, pin, port, attrs, invert):
        self._check_feature("single-ended input/output", pin, attrs,
                            valid_xdrs=(0, 1), valid_attrs=True)
        m = Module()
        i, o, t = self._get_xdr_buffer(m, pin, i_invert=invert, o_invert=invert)
        for bit in range(pin.width):
            m.submodules["{}_{}".format(pin.name, bit)] = Instance("IOBUF",
                i_OEN=t,
                i_I=o[bit],
                o_O=i[bit],
                io_IO=port.io[bit]
            )
        return m

    def get_diff_input(self, pin, p_port, n_port, attrs, invert):
        # TODO
        return False

    def get_diff_output(self, pin, p_port, n_port, attrs, invert):
        # TODO
        return False

    def get_diff_tristate(self, pin, p_port, n_port, attrs, invert):
        # TODO
        return False

    def get_diff_input_output(self, pin, p_port, n_port, attrs, invert):
        # TODO
        return False

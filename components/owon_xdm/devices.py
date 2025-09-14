"""SCPI command sets for different device manufacturers and models."""

class SCPICommands:
    def __init__(self):
        self.measure_voltage_dc = "MEAS:VOLT:DC?"
        self.measure_voltage_ac = "MEAS:VOLT:AC?"
        self.measure_current_dc = "MEAS:CURR:DC?"
        self.measure_current_ac = "MEAS:CURR:AC?"
        self.measure_resistance = "MEAS:RES?"
        self.measure_frequency = "MEAS:FREQ?"
        self.measure_capacitance = "MEAS:CAP?"
        self.measure_temperature = "MEAS:TEMP?"
        self.measure_continuity = "MEAS:CONT?"
        self.measure_diode = "MEAS:DIOD?"
        self.identify = "*IDN?"
        self.reset = "*RST"
        self.remote_enable = "SYST:REM"
        self.fast_mode = None  # Device-specific fast mode command
        self.init_commands = []  # Additional initialization commands

class OwonXDM(SCPICommands):
    def __init__(self):
        super().__init__()
        # OWON XDM1041-specific commands
        self.identify = "*IDN?"
        self.reset = "*RST"
        self.remote_enable = "SYST:REM"
        
        # Measurement commands
        self.measure_voltage_dc = "MEAS1?"  # Primary measurement
        self.measure_voltage_ac = "MEAS1?"  # Use with FUNC1 VOLT:AC
        self.measure_current_dc = "MEAS1?"  # Use with FUNC1 CURR:DC
        self.measure_current_ac = "MEAS1?"  # Use with FUNC1 CURR:AC
        self.measure_resistance = "MEAS1?"  # Use with FUNC1 RES
        self.measure_frequency = "MEAS2?"   # Secondary measurement for AC modes
        self.measure_capacitance = "MEAS1?" # Use with FUNC1 CAP
        self.measure_temperature = "MEAS1?" # Use with FUNC1 TEMP
        self.measure_continuity = "MEAS1?"  # Use with FUNC1 CONT
        self.measure_diode = "MEAS1?"      # Use with FUNC1 DIOD
        
        # Function selection commands
        self.func_voltage_dc = "FUNC1 VOLT:DC"
        self.func_voltage_ac = "FUNC1 VOLT:AC"
        self.func_current_dc = "FUNC1 CURR:DC"
        self.func_current_ac = "FUNC1 CURR:AC"
        self.func_resistance = "FUNC1 RES"
        self.func_capacitance = "FUNC1 CAP"
        self.func_continuity = "FUNC1 CONT"
        self.func_diode = "FUNC1 DIOD"
        
        # Range and mode commands
        self.fast_mode = "RATE F"
        self.auto_range = "AUTO ON"
        self.manual_range = "AUTO OFF"
        self.get_range = "RANGE?"
        self.get_auto = "AUTO?"
        self.get_function = "FUNC1?"
        self.get_secondary = "FUNC2?"
        
        # Special commands for dual display
        self.dual_display_on = "DUAL ON"
        self.dual_display_off = "DUAL OFF"
        
        # Initialization sequence
        self.init_commands = [
            "SYST:REM",     # Enable remote mode
            "RATE F",       # Set fast sampling mode
            "RATE?",        # Verify fast mode
            "AUTO ON",      # Set auto range by default
            "DUAL OFF",     # Start with single display
            "*CLS"          # Clear status
        ]
        
        # Known firmware quirks and workarounds
        self.quirks = {
            "freq_scaling": True,  # Need to scale frequency readings based on range
            "multi_ok": True,      # May return multiple OK\nOK\n responses
            "wait_after_func": True # Need to skip first reading after function change
        }

class Keysight34460A(SCPICommands):
    def __init__(self):
        super().__init__()
        # Keysight-specific commands
        self.init_commands = [
            "DISP:TEXT:CLE",           # Clear display message
            "SENS:VOLT:DC:NPLC 0.02",  # Set integration time for speed
            "TRIG:SOUR IMM",           # Immediate triggering
            "TRIG:COUN INF",           # Continuous measurement
        ]

class RigolDM3068(SCPICommands):
    def __init__(self):
        super().__init__()
        # Rigol-specific commands
        self.init_commands = [
            "RATE:VOLT:DC FAST",      # Fast rate for DC voltage
            "RATE:CURR:DC FAST",      # Fast rate for DC current
            "TRIG:SOUR IMM",          # Immediate triggering
        ]

class Fluke8845A(SCPICommands):
    def __init__(self):
        super().__init__()
        # Fluke-specific commands
        self.measure_voltage_dc = "MEAS:VOLT:DC? 10"  # With autorange max
        self.measure_current_dc = "MEAS:CURR:DC? 1"
        self.init_commands = [
            "TRIG:SOUR IMM",          # Immediate triggering
            "TRIG:COUN INF",          # Continuous readings
            "ZERO:AUTO OFF",          # Disable autozero for speed
        ]

# Map of manufacturer patterns to command sets
DEVICE_COMMANDS = {
    "OWON.*XDM": OwonXDM,
    "Keysight.*34460A|Agilent.*34460A": Keysight34460A,
    "Rigol.*DM3068": RigolDM3068,
    "Fluke.*884[05]A": Fluke8845A,
}

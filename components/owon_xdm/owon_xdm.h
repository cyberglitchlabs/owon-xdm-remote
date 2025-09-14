#pragma once

#include "esphome/core/component.h"
#include "esphome/components/uart/uart.h"
#include "esphome/components/sensor/sensor.h"
#include "esphome/components/text_sensor/text_sensor.h"
#include "esphome/components/select/select.h"
#include "esphome/components/button/button.h"
#include "esphome/components/api/custom_api_device.h"
#include "esphome/core/helpers.h"
#include <regex>
#include <map>

namespace esphome {
namespace scpi_dmm {

// Function selection options for the select component
static const std::string FUNCTION_OPTIONS[] = {
    "DC Voltage",
    "AC Voltage", 
    "DC Current",
    "AC Current",
    "Resistance",
    "Capacitance",
    "Continuity",
    "Diode"
};

// Range selection options
static const std::string RANGE_OPTIONS[] = {
    "Auto",
    "Manual"
};

static const std::string RATE_OPTIONS[] = {
    "Normal",
    "Fast"
};

struct DeviceCommands {
    std::string measure_voltage_dc{"MEAS:VOLT:DC?"};
    std::string measure_voltage_ac{"MEAS:VOLT:AC?"};
    std::string measure_current_dc{"MEAS:CURR:DC?"};
    std::string measure_current_ac{"MEAS:CURR:AC?"};
    std::string measure_resistance{"MEAS:RES?"};
    std::string measure_frequency{"MEAS:FREQ?"};
    std::string measure_capacitance{"MEAS:CAP?"};
    std::string measure_temperature{"MEAS:TEMP?"};
    std::string measure_continuity{"MEAS:CONT?"};
    std::string measure_diode{"MEAS:DIOD?"};
    std::string identify{"*IDN?"};
    std::string reset{"*RST"};
    std::string remote_enable{"SYST:REM"};
    std::string fast_mode{""};
    std::vector<std::string> init_commands{};
};

// Device-specific command sets
static const std::map<std::string, DeviceCommands> DEVICE_COMMANDS = {
    {"OWON_XDM", DeviceCommands{
        .measure_voltage_dc = "MEAS:VOLT?",
        .measure_current_dc = "MEAS:CURR?",
        .fast_mode = "RATE F",
        .init_commands = {"RATE F", "RATE?"}
    }},
    {"KEYSIGHT_34460A", DeviceCommands{
        .init_commands = {
            "DISP:TEXT:CLE",
            "SENS:VOLT:DC:NPLC 0.02",
            "TRIG:SOUR IMM",
            "TRIG:COUN INF"
        }
    }},
    // Add more device-specific commands here
};

enum class MeasurementFunction {
  VOLTAGE_DC,
  VOLTAGE_AC,
  CURRENT_DC,
  CURRENT_AC,
  RESISTANCE,
  CONTINUITY,
  DIODE,
  FREQUENCY,
  TEMPERATURE,
  CAPACITANCE,
  UNKNOWN
};

class SCPIDMM : public Component, public uart::UARTDevice, public api::CustomAPIDevice {
 public:
  SCPIDMM() = default;

  // Primary measurement sensors
  sensor::Sensor *value_sensor{nullptr};
  sensor::Sensor *secondary_value_sensor{nullptr};  // For frequency in AC modes
  
  // State sensors
  text_sensor::TextSensor *function_sensor{nullptr};
  text_sensor::TextSensor *range_sensor{nullptr};
  text_sensor::TextSensor *status_sensor{nullptr};
  text_sensor::TextSensor *idn_sensor{nullptr};

  // Control components
  select::Select *function_select{nullptr};
  select::Select *range_select{nullptr};
  select::Select *rate_select{nullptr};
  button::Button *reset_button{nullptr};
  button::Button *zero_button{nullptr};

  void set_value_sensor(sensor::Sensor *value_sensor) { this->value_sensor = value_sensor; }
  void set_secondary_value_sensor(sensor::Sensor *sensor) { this->secondary_value_sensor = sensor; }
  void set_function_sensor(text_sensor::TextSensor *sensor) { this->function_sensor = sensor; }
  void set_range_sensor(text_sensor::TextSensor *sensor) { this->range_sensor = sensor; }
  void set_status_sensor(text_sensor::TextSensor *sensor) { this->status_sensor = status_sensor; }
  void set_idn_sensor(text_sensor::TextSensor *sensor) { this->idn_sensor = idn_sensor; }
  
  void set_function_select(select::Select *select) { 
    this->function_select = select; 
    this->function_select->add_on_state_callback([this](std::string value, size_t index) {
      this->set_function_(value);
    });
  }
  
  void set_range_select(select::Select *select) { 
    this->range_select = select;
    this->range_select->add_on_state_callback([this](std::string value, size_t index) {
      this->set_range_mode_(value);
    });
  }
  
  void set_rate_select(select::Select *select) { 
    this->rate_select = select;
    this->rate_select->add_on_state_callback([this](std::string value, size_t index) {
      this->set_rate_(value);
    });
  }

  void setup() override {
    // Register services for Home Assistant integration
    register_service(&SCPIDMM::on_relative_zero, "relative_zero");
    register_service(&SCPIDMM::on_reset, "reset");
    register_service(&SCPIDMM::on_set_function, "set_function", {"function"});
    register_service(&SCPIDMM::on_set_range, "set_range", {"mode"});
    register_service(&SCPIDMM::on_set_rate, "set_rate", {"mode"});
    // Query device identification
    this->write_str("*IDN?\r\n");
    
    // Reset to known state
    this->write_str("*RST\r\n");
    
    // Set to remote mode if supported
    this->write_str("SYST:REM\r\n");
  }

  void loop() override {
    while (this->available()) {
      uint8_t c;
      this->read_byte(&c);
      
      if (c == '\n') {
        if (this->rx_buffer_.length() > 0) {
          this->handle_response_(this->rx_buffer_);
          this->rx_buffer_.clear();
        }
      } else if (c != '\r') {
        this->rx_buffer_ += (char) c;
      }
    }

    // Periodically query measurements
    if (millis() - last_query_ >= query_interval_) {
      query_measurement_();
      last_query_ = millis();
    }
  }

  // Send SCPI command
  void send_command(const std::string &cmd) {
    this->write_str(cmd + "\r\n");
  }

  // Set measurement function
  void set_function(const std::string &function) {
    this->send_command(function);
    current_function_ = parse_function_(function);
    if (this->function_sensor != nullptr) {
      this->function_sensor->publish_state(function);
    }
  }

  void query_measurement_() {
    switch (current_function_) {
      case MeasurementFunction::VOLTAGE_DC:
        send_command("MEAS:VOLT:DC?");
        break;
      case MeasurementFunction::VOLTAGE_AC:
        send_command("MEAS:VOLT:AC?");
        break;
      case MeasurementFunction::CURRENT_DC:
        send_command("MEAS:CURR:DC?");
        break;
      case MeasurementFunction::CURRENT_AC:
        send_command("MEAS:CURR:AC?");
        break;
      case MeasurementFunction::RESISTANCE:
        send_command("MEAS:RES?");
        break;
      case MeasurementFunction::FREQUENCY:
        send_command("MEAS:FREQ?");
        break;
      case MeasurementFunction::CAPACITANCE:
        send_command("MEAS:CAP?");
        break;
      case MeasurementFunction::TEMPERATURE:
        send_command("MEAS:TEMP?");
        break;
      case MeasurementFunction::CONTINUITY:
        send_command("MEAS:CONT?");
        break;
      case MeasurementFunction::DIODE:
        send_command("MEAS:DIOD?");
        break;
      default:
        send_command("MEAS?");
        break;
    }
  }

  void handle_response_(const std::string &response) {
    if (response.empty())
      return;

    // Handle IDN response
    if (waiting_for_idn_) {
      if (this->idn_sensor != nullptr) {
        this->idn_sensor->publish_state(response);
      }
      waiting_for_idn_ = false;
      return;
    }

    // Try to parse as a numeric value
    try {
      float value = parse_numeric_response_(response);
      if (this->value_sensor != nullptr) {
        this->value_sensor->publish_state(value);
      }
    } catch (...) {
      // Non-numeric response - could be status or error
      ESP_LOGW("scpi_dmm", "Non-numeric response: %s", response.c_str());
    }
  }

  float parse_numeric_response_(const std::string &response) {
    return std::stof(response);
  }

  MeasurementFunction parse_function_(const std::string &function) {
    std::string upper = function;
    std::transform(upper.begin(), upper.end(), upper.begin(), ::toupper);
    
    if (upper.find("VOLT:DC") != std::string::npos) return MeasurementFunction::VOLTAGE_DC;
    if (upper.find("VOLT:AC") != std::string::npos) return MeasurementFunction::VOLTAGE_AC;
    if (upper.find("CURR:DC") != std::string::npos) return MeasurementFunction::CURRENT_DC;
    if (upper.find("CURR:AC") != std::string::npos) return MeasurementFunction::CURRENT_AC;
    if (upper.find("RES") != std::string::npos) return MeasurementFunction::RESISTANCE;
    if (upper.find("CONT") != std::string::npos) return MeasurementFunction::CONTINUITY;
    if (upper.find("DIOD") != std::string::npos) return MeasurementFunction::DIODE;
    if (upper.find("FREQ") != std::string::npos) return MeasurementFunction::FREQUENCY;
    if (upper.find("TEMP") != std::string::npos) return MeasurementFunction::TEMPERATURE;
    if (upper.find("CAP") != std::string::npos) return MeasurementFunction::CAPACITANCE;
    
    return MeasurementFunction::UNKNOWN;
  }

 protected:
  std::string rx_buffer_;
  MeasurementFunction current_function_{MeasurementFunction::UNKNOWN};
  bool waiting_for_idn_{true};
  uint32_t last_query_{0};
  static const uint32_t query_interval_{100}; // Query every 100ms
};

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami

Item {
    id: fullRoot

    Layout.minimumWidth: Kirigami.Units.gridUnit * 22
    Layout.minimumHeight: Kirigami.Units.gridUnit * 26
    Layout.preferredWidth: Kirigami.Units.gridUnit * 24
    Layout.preferredHeight: Kirigami.Units.gridUnit * 28

    readonly property var battery: root.sensorData.battery || {}
    readonly property var solar: root.sensorData.solar || {}
    readonly property var multiplus: root.sensorData.multiplus || {}
    readonly property var grid: root.sensorData.grid || {}
    readonly property var system: root.sensorData.system || {}
    readonly property var alarms: root.sensorData.alarms || []
    readonly property bool connected: root.sensorData.connected || false

    QQC2.ScrollView {
        anchors.fill: parent
        contentWidth: availableWidth

        ColumnLayout {
            width: parent.width
            spacing: Kirigami.Units.largeSpacing

            // Top Header: Status & Last update
            RowLayout {
                Layout.fillWidth: true

                Kirigami.Icon {
                    source: fullRoot.connected ? "security-high" : "network-disconnect"
                    implicitWidth: Kirigami.Units.iconSizes.smallMedium
                    implicitHeight: Kirigami.Units.iconSizes.smallMedium
                    color: fullRoot.connected ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.negativeTextColor
                }

                ColumnLayout {
                    spacing: 0
                    PlasmaComponents3.Label {
                        text: i18n("Victron Cerbo GX")
                        font.bold: true
                        font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.1
                    }
                    PlasmaComponents3.Label {
                        text: fullRoot.connected ? (system.ess_mode || i18n("Connected")) : i18n("Offline / Connecting...")
                        font.pointSize: Kirigami.Theme.smallFont.pointSize
                        opacity: 0.7
                        elide: Text.ElideRight
                        Layout.maximumWidth: Kirigami.Units.gridUnit * 16
                    }
                }

                Item { Layout.fillWidth: true }

                PlasmaComponents3.Button {
                    icon.name: "view-refresh"
                    display: PlasmaComponents3.AbstractButton.IconOnly
                    onClicked: root.refreshSensors()
                }
            }

            // Alarms Warning if active
            Kirigami.InlineMessage {
                Layout.fillWidth: true
                visible: fullRoot.alarms && fullRoot.alarms.length > 0
                type: Kirigami.MessageType.Error
                text: fullRoot.alarms ? fullRoot.alarms.join("\n") : ""
            }

            // ================= BATTERY CARD =================
            Kirigami.Card {
                Layout.fillWidth: true

                header: RowLayout {
                    Kirigami.Icon {
                        source: battery.is_charging ? "battery-charging" : "battery"
                        implicitWidth: Kirigami.Units.iconSizes.smallMedium
                        implicitHeight: Kirigami.Units.iconSizes.smallMedium
                        color: {
                            var s = battery.soc_pct || 0;
                            if (s >= 50) return Kirigami.Theme.positiveTextColor;
                            if (s >= 20) return Kirigami.Theme.neutralTextColor;
                            return Kirigami.Theme.negativeTextColor;
                        }
                    }
                    PlasmaComponents3.Label {
                        text: i18n("Battery Bank (Eco-Worthy UP16S)")
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    PlasmaComponents3.Label {
                        text: battery.soc_pct !== undefined ? battery.soc_pct.toFixed(1) + "%" : "--%"
                        font.bold: true
                        font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.2
                    }
                }

                contentItem: ColumnLayout {
                    spacing: Kirigami.Units.smallSpacing

                    // SoC Bar
                    QQC2.ProgressBar {
                        Layout.fillWidth: true
                        from: 0
                        to: 100
                        value: battery.soc_pct || 0
                    }

                    GridLayout {
                        columns: 2
                        rowSpacing: 4
                        columnSpacing: Kirigami.Units.largeSpacing
                        Layout.fillWidth: true

                        PlasmaComponents3.Label { text: i18n("Power / Current:"); opacity: 0.7 }
                        PlasmaComponents3.Label {
                            text: {
                                var p = battery.power_w || 0;
                                var a = battery.current_a || 0;
                                var sign = p >= 0 ? "+" : "";
                                var flow = p > 10 ? i18n(" (Charging)") : (p < -10 ? i18n(" (Discharging)") : i18n(" (Idle)"));
                                return sign + p.toFixed(0) + " W / " + sign + a.toFixed(1) + " A" + flow;
                            }
                            font.bold: true
                        }

                        PlasmaComponents3.Label { text: i18n("Pack Voltage / Temp:"); opacity: 0.7 }
                        PlasmaComponents3.Label {
                            text: (battery.voltage_v ? battery.voltage_v.toFixed(2) + " V" : "--") + "  |  " +
                                  (battery.temperature_c ? battery.temperature_c.toFixed(1) + " °C" : "--")
                        }

                        PlasmaComponents3.Label { text: i18n("Cell Balance (Min/Max):"); opacity: 0.7 }
                        PlasmaComponents3.Label {
                            text: {
                                var minV = battery.min_cell_v ? battery.min_cell_v.toFixed(3) : "--";
                                var maxV = battery.max_cell_v ? battery.max_cell_v.toFixed(3) : "--";
                                var delta = battery.cell_imbalance_mv !== undefined && battery.cell_imbalance_mv !== null ? " (Δ " + battery.cell_imbalance_mv + " mV)" : "";
                                return minV + " V / " + maxV + " V" + delta;
                            }
                        }

                        PlasmaComponents3.Label { text: i18n("Health & Modules:"); opacity: 0.7 }
                        PlasmaComponents3.Label {
                            text: (battery.soh_pct ? battery.soh_pct + "% SOH" : "100% SOH") + "  |  " +
                                  (battery.modules_online ? battery.modules_online + "/3 Modules (" + (battery.installed_capacity_ah || 300) + " Ah)" : "3 Modules")
                        }
                    }
                }
            }

            // ================= SOLAR MPPT CARD =================
            Kirigami.Card {
                Layout.fillWidth: true

                header: RowLayout {
                    Kirigami.Icon {
                        source: "weather-clear"
                        implicitWidth: Kirigami.Units.iconSizes.smallMedium
                        implicitHeight: Kirigami.Units.iconSizes.smallMedium
                        color: Kirigami.Theme.neutralTextColor
                    }
                    PlasmaComponents3.Label {
                        text: i18n("Solar MPPT (SmartSolar 150/45)")
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    PlasmaComponents3.Label {
                        text: (solar.power_w ? solar.power_w.toFixed(0) : "0") + " W"
                        font.bold: true
                        font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.2
                        color: Kirigami.Theme.neutralTextColor
                    }
                }

                contentItem: GridLayout {
                    columns: 2
                    rowSpacing: 4
                    columnSpacing: Kirigami.Units.largeSpacing
                    Layout.fillWidth: true

                    PlasmaComponents3.Label { text: i18n("Today's Yield:"); opacity: 0.7 }
                    PlasmaComponents3.Label {
                        text: (solar.yield_today_kwh ? solar.yield_today_kwh.toFixed(2) + " kWh" : "0.0 kWh") +
                              (solar.max_power_today_w ? " (Peak: " + Math.round(solar.max_power_today_w) + " W)" : "")
                        font.bold: true
                    }

                    PlasmaComponents3.Label { text: i18n("PV Array (V / A):"); opacity: 0.7 }
                    PlasmaComponents3.Label {
                        text: (solar.pv_voltage_v ? solar.pv_voltage_v.toFixed(1) + " V" : "--") + " / " +
                              (solar.pv_current_a ? solar.pv_current_a.toFixed(1) + " A" : "--")
                    }

                    PlasmaComponents3.Label { text: i18n("Status / Mode:"); opacity: 0.7 }
                    PlasmaComponents3.Label {
                        text: (solar.mppt_mode || "Active") + " (" + (solar.state || "External Control") + ")"
                    }
                }
            }

            // ================= MULTIPLUS & GRID CARD =================
            Kirigami.Card {
                Layout.fillWidth: true

                header: RowLayout {
                    Kirigami.Icon {
                        source: "network-wired"
                        implicitWidth: Kirigami.Units.iconSizes.smallMedium
                        implicitHeight: Kirigami.Units.iconSizes.smallMedium
                    }
                    PlasmaComponents3.Label {
                        text: i18n("MultiPlus-II & Grid")
                        font.bold: true
                    }
                    Item { Layout.fillWidth: true }
                    PlasmaComponents3.Label {
                        text: multiplus.state || i18n("On")
                        font.bold: true
                    }
                }

                contentItem: GridLayout {
                    columns: 2
                    rowSpacing: 4
                    columnSpacing: Kirigami.Units.largeSpacing
                    Layout.fillWidth: true

                    PlasmaComponents3.Label { text: i18n("Grid Flow:"); opacity: 0.7 }
                    PlasmaComponents3.Label {
                        text: {
                            var gW = grid.power_w || 0;
                            var label = gW > 10 ? i18n("Importing") : (gW < -10 ? i18n("Exporting") : i18n("Balanced"));
                            return Math.abs(gW).toFixed(0) + " W " + label + " (" + (grid.voltage_v ? grid.voltage_v.toFixed(1) + " V" : "") + ")";
                        }
                        font.bold: true
                        color: (grid.power_w || 0) < -10 ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.textColor
                    }

                    PlasmaComponents3.Label { text: i18n("House Consumption:"); opacity: 0.7 }
                    PlasmaComponents3.Label {
                        text: (system.consumption_power_w ? system.consumption_power_w.toFixed(0) + " W" : "--")
                    }

                    PlasmaComponents3.Label { text: i18n("Inverter AC Out / In:"); opacity: 0.7 }
                    PlasmaComponents3.Label {
                        text: (multiplus.output_power_w ? multiplus.output_power_w.toFixed(0) + " W" : "0 W") + " out / " +
                              (multiplus.input_power_w ? multiplus.input_power_w.toFixed(0) + " W" : "0 W") + " in"
                    }

                    PlasmaComponents3.Label { text: i18n("DC Conversion:"); opacity: 0.7 }
                    PlasmaComponents3.Label {
                        text: (multiplus.dc_power_w ? multiplus.dc_power_w.toFixed(0) + " W" : "--") + " (" +
                              (multiplus.dc_current_a ? multiplus.dc_current_a.toFixed(1) + " A" : "--") + ")"
                    }
                }
            }
        }
    }
}

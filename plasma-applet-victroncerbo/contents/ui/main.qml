import QtQuick
import QtQuick.Layouts
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    Plasmoid.backgroundHints: PlasmaCore.Types.DefaultBackground | PlasmaCore.Types.ConfigurableBackground
    Plasmoid.title: i18n("Victron Energy Monitor")

    property var sensorData: ({
        status: "connecting",
        connected: false,
        battery: {},
        solar: {},
        multiplus: {},
        grid: {},
        system: {},
        alarms: []
    })

    readonly property string httpUrl: Plasmoid.configuration.httpUrl || "http://127.0.0.1:8766/sensors"
    readonly property int pollIntervalMs: Math.max(1, Plasmoid.configuration.updateInterval || 2) * 1000

    function refreshSensors() {
        var xhr = new XMLHttpRequest();
        xhr.open("GET", root.httpUrl, true);
        xhr.timeout = 1500;
        xhr.onreadystatechange = function() {
            if (xhr.readyState === XMLHttpRequest.DONE) {
                if (xhr.status === 200) {
                    try {
                        var parsed = JSON.parse(xhr.responseText);
                        if (parsed && typeof parsed === "object") {
                            root.sensorData = parsed;
                        }
                    } catch (e) {
                        // ignore parse error
                    }
                }
            }
        };
        xhr.send();
    }

    Timer {
        id: refreshTimer
        interval: root.pollIntervalMs
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refreshSensors()
    }

    compactRepresentation: CompactRepresentation {
        id: compactRep
    }

    fullRepresentation: FullRepresentation {
        id: fullRep
    }

    toolTipMainText: i18n("Victron Cerbo GX")
    toolTipSubText: {
        if (!root.sensorData || !root.sensorData.connected) {
            return i18n("Cerbo GX Offline / Connecting...");
        }
        var b = root.sensorData.battery || {};
        var s = root.sensorData.solar || {};
        var g = root.sensorData.grid || {};
        var lines = [];
        if (b.soc_pct !== undefined && b.soc_pct !== null) {
            lines.push(i18n("Battery: %1% (%2 W)", b.soc_pct, (b.power_w || 0).toFixed(0)));
        }
        if (s.power_w !== undefined && s.power_w !== null) {
            lines.push(i18n("Solar: %1 W (Today: %2 kWh)", (s.power_w || 0).toFixed(0), (s.yield_today_kwh || 0).toFixed(1)));
        }
        if (g.power_w !== undefined && g.power_w !== null) {
            lines.push(i18n("Grid: %1 W", (g.power_w || 0).toFixed(0)));
        }
        return lines.join("\n");
    }
}

import QtQuick
import QtQuick.Layouts
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PlasmaComponents3
import org.kde.plasma.plasmoid
import org.kde.kirigami as Kirigami

Item {
    id: compactRoot

    readonly property bool isVertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical
    readonly property var battery: root.sensorData.battery || {}
    readonly property var solar: root.sensorData.solar || {}
    readonly property var grid: root.sensorData.grid || {}
    readonly property bool connected: root.sensorData.connected || false

    readonly property color socColor: {
        var soc = battery.soc_pct || 0;
        if (soc >= 50) return Kirigami.Theme.positiveTextColor;
        if (soc >= 20) return Kirigami.Theme.neutralTextColor;
        return Kirigami.Theme.negativeTextColor;
    }

    Layout.minimumWidth: isVertical ? Kirigami.Units.gridUnit * 2 : rowLayout.implicitWidth + Kirigami.Units.smallSpacing * 2
    Layout.minimumHeight: isVertical ? colLayout.implicitHeight + Kirigami.Units.smallSpacing * 2 : Kirigami.Units.gridUnit * 2
    Layout.preferredWidth: Layout.minimumWidth
    Layout.preferredHeight: Layout.minimumHeight

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
            root.expanded = !root.expanded;
        }
    }

    // Horizontal representation
    RowLayout {
        id: rowLayout
        visible: !compactRoot.isVertical
        anchors.centerIn: parent
        spacing: Kirigami.Units.smallSpacing

        // Battery item
        RowLayout {
            spacing: 2
            Kirigami.Icon {
                source: battery.is_charging ? "battery-charging" : "battery"
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
                color: compactRoot.socColor
            }
            PlasmaComponents3.Label {
                text: compactRoot.connected && battery.soc_pct !== undefined ? Math.round(battery.soc_pct) + "%" : "--%"
                font.bold: true
                font.pointSize: Kirigami.Theme.smallFont.pointSize
                color: compactRoot.socColor
            }
        }

        // Solar item
        RowLayout {
            visible: Plasmoid.configuration.showSolarInCompact !== false && (solar.power_w || 0) > 0
            spacing: 2
            Kirigami.Icon {
                source: "weather-clear"
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
                color: Kirigami.Theme.neutralTextColor
            }
            PlasmaComponents3.Label {
                text: solar.power_w ? Math.round(solar.power_w) + "W" : ""
                font.pointSize: Kirigami.Theme.smallFont.pointSize
            }
        }

        // Grid item
        RowLayout {
            visible: Plasmoid.configuration.showGridInCompact !== false && grid.power_w !== undefined && grid.power_w !== null
            spacing: 2
            Kirigami.Icon {
                source: (grid.power_w || 0) >= 0 ? "network-wired" : "arrow-up"
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
                color: (grid.power_w || 0) < -10 ? Kirigami.Theme.positiveTextColor : Kirigami.Theme.textColor
            }
            PlasmaComponents3.Label {
                text: grid.power_w !== undefined ? Math.abs(Math.round(grid.power_w)) + "W" : ""
                font.pointSize: Kirigami.Theme.smallFont.pointSize
            }
        }
    }

    // Vertical representation
    ColumnLayout {
        id: colLayout
        visible: compactRoot.isVertical
        anchors.centerIn: parent
        spacing: 2

        Kirigami.Icon {
            Layout.alignment: Qt.AlignHCenter
            source: battery.is_charging ? "battery-charging" : "battery"
            implicitWidth: Kirigami.Units.iconSizes.smallMedium
            implicitHeight: Kirigami.Units.iconSizes.smallMedium
            color: compactRoot.socColor
        }
        PlasmaComponents3.Label {
            Layout.alignment: Qt.AlignHCenter
            text: compactRoot.connected && battery.soc_pct !== undefined ? Math.round(battery.soc_pct) + "%" : "--"
            font.bold: true
            font.pointSize: Kirigami.Theme.smallFont.pointSize
            color: compactRoot.socColor
        }
    }
}

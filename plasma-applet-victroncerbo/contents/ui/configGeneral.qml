import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kquickcontrols as KQuickControls

KQuickControls.SimpleKCM {
    id: root

    property alias cfg_updateInterval: intervalSpin.value
    property alias cfg_showSolarInCompact: solarCheckBox.checked
    property alias cfg_showGridInCompact: gridCheckBox.checked
    property alias cfg_dataPath: dataPathField.text

    Kirigami.FormLayout {
        QQC2.SpinBox {
            id: intervalSpin
            Kirigami.FormData.label: i18n("Update interval (seconds):")
            from: 1
            to: 60
            stepSize: 1
        }

        QQC2.CheckBox {
            id: solarCheckBox
            Kirigami.FormData.label: i18n("Compact Display:")
            text: i18n("Show solar power badge in panel")
        }

        QQC2.CheckBox {
            id: gridCheckBox
            text: i18n("Show grid power badge in panel")
        }

        QQC2.TextField {
            id: dataPathField
            Kirigami.FormData.label: i18n("Sensor JSON Path:")
            Layout.fillWidth: true
            placeholderText: "/dev/shm/victron_sensors.json"
        }
    }
}

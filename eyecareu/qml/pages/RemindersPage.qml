import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../components"

Flickable {
    id: page
    contentWidth: width
    contentHeight: column.implicitHeight + Theme.pad * 2
    clip: true

    ScrollBar.vertical: ScrollBar {}

    ColumnLayout {
        id: column
        x: Theme.pad
        y: Theme.pad
        width: page.width - Theme.pad * 2
        spacing: Theme.gap

        Card {
            title: "Break reminder"
            Layout.fillWidth: true
            ToggleRow {
                label: "Remind me to take breaks"
                description: "A notification every time the interval elapses while you are active."
                checked: core.breakReminderEnabled
                onActivated: core.breakReminderEnabled = value
            }
            SliderRow {
                label: "Interval"
                from: 20
                to: 180
                stepSize: 5
                value: core.breakIntervalMinutes
                suffix: " min"
                enabledControl: core.breakReminderEnabled
                onMoved: core.breakIntervalMinutes = value
            }
        }

        Card {
            title: "Low light reminder"
            Layout.fillWidth: true
            ToggleRow {
                label: "Warn me when the room is too dark"
                description: "Uses the panel's ambient-light sensor when the monitor exposes one; "
                             + "otherwise this reminder stays quiet."
                checked: core.lowLightReminderEnabled
                onActivated: core.lowLightReminderEnabled = value
            }
            SliderRow {
                label: "Brightness threshold"
                from: 0
                to: 500
                stepSize: 10
                value: core.lowLightThreshold
                suffix: " lux"
                enabledControl: core.lowLightReminderEnabled
                onMoved: core.lowLightThreshold = value
            }
        }

        Card {
            title: "Distance and posture"
            Layout.fillWidth: true
            ToggleRow {
                label: "Distance reminder"
                checked: core.distanceReminderEnabled
                onActivated: core.distanceReminderEnabled = value
            }
            SliderRow {
                label: "Recommended distance"
                from: 30
                to: 120
                stepSize: 5
                value: core.distanceCm
                suffix: " cm"
                enabledControl: core.distanceReminderEnabled
                onMoved: core.distanceCm = value
            }
            ToggleRow {
                label: "Posture reminder"
                description: "Periodically check that you are sitting comfortably."
                checked: core.postureReminderEnabled
                onActivated: core.postureReminderEnabled = value
            }
        }

        Item { Layout.fillHeight: true; implicitHeight: 8 }
    }
}

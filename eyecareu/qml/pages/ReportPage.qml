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

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.gap
            StatCard {
                label: "Today"
                value: core.todayMinutes + " min"
                caption: core.goalPercent + "% of " + core.dailyGoalMinutes + " min goal"
                Layout.fillWidth: true
            }
            StatCard {
                label: "Longest stretch"
                value: core.todayStretchMinutes + " min"
                accent: Theme.warn
                Layout.fillWidth: true
            }
            StatCard {
                label: "Breaks"
                value: String(core.todayBreaks)
                accent: "#3f6fb5"
                Layout.fillWidth: true
            }
        }

        Card {
            title: "Last 7 days"
            Layout.fillWidth: true

            Repeater {
                model: core.weekData
                delegate: RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gap
                    Text {
                        text: modelData.day
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                        Layout.preferredWidth: 96
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        height: 18
                        radius: 9
                        color: Theme.surfaceAlt
                        Rectangle {
                            height: parent.height
                            radius: parent.radius
                            color: Theme.accent
                            width: parent.width * Math.min(1, modelData.minutes
                                   / Math.max(1, core.dailyGoalMinutes))
                        }
                    }
                    Text {
                        text: modelData.minutes + " min"
                        color: Theme.text
                        font.pixelSize: Theme.fontSmall
                        Layout.preferredWidth: 70
                        horizontalAlignment: Text.AlignRight
                    }
                    Text {
                        text: modelData.breaks + " breaks"
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                        Layout.preferredWidth: 80
                        horizontalAlignment: Text.AlignRight
                    }
                }
            }
        }

        Card {
            title: "Report settings"
            Layout.fillWidth: true
            ToggleRow {
                label: "Record screen time"
                description: "All data stays on this machine, under ~/.local/state/eyecareu."
                checked: core.reportEnabled
                onActivated: core.reportEnabled = value
            }
            SliderRow {
                label: "Daily goal"
                from: 60
                to: 960
                stepSize: 30
                value: core.dailyGoalMinutes
                suffix: " min"
                onMoved: core.dailyGoalMinutes = value
            }
            Button {
                text: "Clear history"
                onClicked: core.clearReport()
            }
        }

        Item { Layout.fillHeight: true; implicitHeight: 8 }
    }
}

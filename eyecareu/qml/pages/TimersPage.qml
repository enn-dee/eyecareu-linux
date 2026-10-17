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

    function formatTime(seconds) {
        var s = Math.max(0, Math.round(seconds))
        var m = Math.floor(s / 60)
        var r = s % 60
        return (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r
    }

    ColumnLayout {
        id: column
        x: Theme.pad
        y: Theme.pad
        width: page.width - Theme.pad * 2
        spacing: Theme.gap

        // -- 20-20-20 -----------------------------------------------------
        Card {
            title: "20-20-20 rule"
            Layout.fillWidth: true

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.pad

                TimerRing {
                    progress: core.twentyProgress
                    centerText: page.formatTime(core.twentyRemaining)
                    caption: core.twentyPhase
                    ringColor: Theme.accent
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gap

                    Text {
                        text: core.twentyRunning
                              ? (core.twentyPaused ? "Paused" : "Running - " + core.twentyPhase)
                              : "Stopped"
                        color: Theme.text
                        font.pixelSize: Theme.fontTitle
                        font.bold: true
                    }
                    Text {
                        text: "Completed cycles: " + core.twentyCycles
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                    }

                    RowLayout {
                        spacing: 8
                        Button {
                            text: core.twentyRunning ? (core.twentyPaused ? "Resume" : "Pause") : "Start"
                            highlighted: !core.twentyRunning
                            onClicked: core.toggleTwenty()
                        }
                        Button { text: "Skip"; onClicked: core.skipTwenty(); enabled: core.twentyRunning }
                        Button { text: "Stop"; onClicked: core.stopTwenty(); enabled: core.twentyRunning }
                        Switch {
                            text: "On"
                            Binding on checked {
                                value: core.twentyRunning
                                restoreMode: Binding.RestoreBindingOrValue
                            }
                            onToggled: core.setTwentyEnabled(checked)
                        }
                    }

                    SliderRow {
                        label: "Work interval"
                        from: 5
                        to: 90
                        value: core.twentyWorkMinutes
                        suffix: " min"
                        onMoved: core.twentyWorkMinutes = value
                    }
                    SliderRow {
                        label: "Break length"
                        from: 10
                        to: 120
                        stepSize: 5
                        value: core.twentyBreakSeconds
                        suffix: " s"
                        onMoved: core.twentyBreakSeconds = value
                    }
                }
            }
        }

        // -- Pomodoro -----------------------------------------------------
        Card {
            title: "Pomodoro"
            Layout.fillWidth: true

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.pad

                TimerRing {
                    progress: core.pomodoroProgress
                    centerText: page.formatTime(core.pomodoroRemaining)
                    caption: core.pomodoroPhase
                    ringColor: core.pomodoroPhase === "work" ? Theme.accent : "#3f6fb5"
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: Theme.gap

                    Text {
                        text: core.pomodoroRunning
                              ? (core.pomodoroPaused ? "Paused" : "Running - " + core.pomodoroPhase)
                              : "Stopped"
                        color: Theme.text
                        font.pixelSize: Theme.fontTitle
                        font.bold: true
                    }
                    Text {
                        text: "Completed work blocks: " + core.pomodoroCycles
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                    }

                    RowLayout {
                        spacing: 8
                        Button {
                            text: core.pomodoroRunning ? (core.pomodoroPaused ? "Resume" : "Pause") : "Start"
                            highlighted: !core.pomodoroRunning
                            onClicked: core.togglePomodoro()
                        }
                        Button { text: "Skip"; onClicked: core.skipPomodoro(); enabled: core.pomodoroRunning }
                        Button { text: "Stop"; onClicked: core.stopPomodoro(); enabled: core.pomodoroRunning }
                        Switch {
                            text: "On"
                            Binding on checked {
                                value: core.pomodoroRunning
                                restoreMode: Binding.RestoreBindingOrValue
                            }
                            onToggled: core.setPomodoroEnabled(checked)
                        }
                    }
                }
            }

            GridLayout {
                columns: 2
                columnSpacing: Theme.gap * 2
                Layout.fillWidth: true

                SliderRow {
                    label: "Work"
                    from: 5
                    to: 90
                    value: core.pomodoroWorkMinutes
                    suffix: " min"
                    onMoved: core.pomodoroWorkMinutes = value
                }
                SliderRow {
                    label: "Short break"
                    from: 1
                    to: 30
                    value: core.pomodoroShortBreakMinutes
                    suffix: " min"
                    onMoved: core.pomodoroShortBreakMinutes = value
                }
                SliderRow {
                    label: "Long break"
                    from: 5
                    to: 60
                    value: core.pomodoroLongBreakMinutes
                    suffix: " min"
                    onMoved: core.pomodoroLongBreakMinutes = value
                }
                SliderRow {
                    label: "Blocks before long break"
                    from: 2
                    to: 8
                    value: core.pomodoroCyclesBeforeLong
                    onMoved: core.pomodoroCyclesBeforeLong = value
                }
            }

            ToggleRow {
                label: "Start the next block automatically"
                checked: core.pomodoroAutoStart
                onActivated: core.pomodoroAutoStart = value
            }
        }

        Item { Layout.fillHeight: true; implicitHeight: 8 }
    }
}

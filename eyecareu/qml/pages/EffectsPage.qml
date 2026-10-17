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

        Rectangle {
            visible: core.effectsMode === "overlay"
            Layout.fillWidth: true
            color: Theme.surfaceAlt
            radius: Theme.radiusSmall
            border.color: Theme.border
            border.width: 1
            implicitHeight: notice.implicitHeight + 20
            Text {
                id: notice
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: 12
                text: core.effectsMode === "overlay"
                      ? "This session has no colour-ramp API (Wayland), so these effects are "
                        + "applied as a translucent full-screen overlay that warms and dims the "
                        + "screen. On X11 the same settings drive the real gamma ramp instead."
                      : "Software colour effects are unavailable on this session."
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                wrapMode: Text.WordWrap
            }
        }

        Card {
            title: "Night light"
            Layout.fillWidth: true
            ToggleRow {
                label: "Enable night light"
                checked: core.nightLightEnabled
                onActivated: core.nightLightEnabled = value
            }
            SliderRow {
                label: "Colour temperature"
                from: 2000
                to: 6500
                stepSize: 100
                value: core.nightLightTemperature
                suffix: " K"
                enabledControl: core.nightLightEnabled
                onMoved: core.nightLightTemperature = value
            }
            SliderRow {
                label: "Strength"
                from: 0
                to: 100
                value: core.nightLightStrength
                suffix: " %"
                enabledControl: core.nightLightEnabled
                onMoved: core.nightLightStrength = value
            }
        }

        Card {
            title: "Low blue light"
            Layout.fillWidth: true
            ToggleRow {
                label: "Enable low blue light"
                checked: core.lowBlueLightEnabled
                onActivated: core.lowBlueLightEnabled = value
            }
            SliderRow {
                label: "Level"
                from: 0
                to: 100
                value: core.lowBlueLightLevel
                suffix: " %"
                enabledControl: core.lowBlueLightEnabled
                onMoved: core.lowBlueLightLevel = value
            }
        }

        Card {
            title: "Software dimming"
            Layout.fillWidth: true
            ToggleRow {
                label: "Dim below the monitor minimum"
                description: "Scales the colour ramp; useful at night when the panel is still too bright."
                checked: core.softwareDimmingEnabled
                onActivated: core.softwareDimmingEnabled = value
            }
            SliderRow {
                label: "Brightness"
                from: 5
                to: 100
                value: core.softwareDimmingLevel
                suffix: " %"
                enabledControl: core.softwareDimmingEnabled
                onMoved: core.softwareDimmingLevel = value
            }
        }

        Card {
            title: "Comfort"
            Layout.fillWidth: true
            ToggleRow {
                label: "Warm tint"
                description: "A gentle warm shift for long reading sessions."
                checked: core.warmTintEnabled
                onActivated: core.warmTintEnabled = value
            }
            SliderRow {
                label: "Warm tint strength"
                from: 0
                to: 100
                value: core.warmTintStrength
                suffix: " %"
                enabledControl: core.warmTintEnabled
                onMoved: core.warmTintStrength = value
            }
            ToggleRow {
                label: "Text clarity boost"
                description: "A mild contrast/gamma adjustment for text legibility."
                checked: core.clearTypeEnabled
                onActivated: core.clearTypeEnabled = value
            }
        }

        Card {
            title: "Circadian mode"
            Layout.fillWidth: true
            ToggleRow {
                label: "Follow the time of day"
                description: "Shift from a neutral day temperature to a warm night temperature."
                checked: core.circadianEnabled
                onActivated: core.circadianEnabled = value
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gap
                SliderRow {
                    label: "Day temperature"
                    from: 4000
                    to: 10000
                    stepSize: 100
                    value: core.circadianDayTemperature
                    suffix: " K"
                    enabledControl: core.circadianEnabled
                    onMoved: core.circadianDayTemperature = value
                }
                SliderRow {
                    label: "Night temperature"
                    from: 2000
                    to: 6000
                    stepSize: 100
                    value: core.circadianNightTemperature
                    suffix: " K"
                    enabledControl: core.circadianEnabled
                    onMoved: core.circadianNightTemperature = value
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.gap
                TextField {
                    text: core.circadianSunrise
                    enabled: core.circadianEnabled
                    placeholderText: "Sunrise HH:MM"
                    Layout.fillWidth: true
                    onEditingFinished: core.circadianSunrise = text
                }
                TextField {
                    text: core.circadianSunset
                    enabled: core.circadianEnabled
                    placeholderText: "Sunset HH:MM"
                    Layout.fillWidth: true
                    onEditingFinished: core.circadianSunset = text
                }
            }
            Text {
                text: core.circadianEnabled
                      ? ("Current phase: " + core.circadianPhase + "  •  "
                         + core.circadianCurrentTemperature + " K")
                      : "Disabled"
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
            }
        }

        Button {
            text: "Reset all software effects"
            onClicked: core.resetEffects()
        }

        Item { Layout.fillHeight: true; implicitHeight: 8 }
    }
}

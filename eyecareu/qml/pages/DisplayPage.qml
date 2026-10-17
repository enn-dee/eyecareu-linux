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
            title: "Monitor"
            Layout.fillWidth: true

            ComboBox {
                id: monitorCombo
                Layout.fillWidth: true
                model: core.monitors
                textRole: "name"
                currentIndex: {
                    var list = core.monitors
                    for (var i = 0; i < list.length; i++) {
                        if (list[i].displayId === core.selectedDisplayId) return i
                    }
                    return list.length > 0 ? 0 : -1
                }
                onActivated: function (index) {
                    if (index >= 0 && index < core.monitors.length)
                        core.selectedDisplayId = core.monitors[index].displayId
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Chip { text: core.selectedMonitor.manufacturer || "Display" }
                Chip { text: core.selectedMonitor.online ? "DDC/CI"
                             : (core.selectedMonitor.backlight ? "backlight" : "offline") }
                Chip { visible: core.selectedMonitor.model && core.selectedMonitor.model.length > 0
                       text: core.selectedMonitor.model }
                Item { Layout.fillWidth: true }
                Text {
                    text: "Firmware: " + (core.selectedMonitor.firmware || "-")
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
            }
        }

        Card {
            title: "Hardware controls (DDC/CI)"
            Layout.fillWidth: true

            SliderRow {
                label: "Brightness"
                value: core.selectedMonitor.brightness !== undefined ? core.selectedMonitor.brightness : 0
                enabledControl: core.selectedMonitor.brightnessSupported === true
                onMoved: core.setBrightness(core.selectedDisplayId, value)
            }

            SliderRow {
                label: "Volume"
                value: core.selectedMonitor.volume !== undefined ? core.selectedMonitor.volume : 0
                enabledControl: core.selectedMonitor.volumeSupported === true
                onMoved: core.setVolume(core.selectedDisplayId, value)
            }

            ToggleRow {
                visible: core.selectedMonitor.volumeSupported === true
                label: "Mute"
                checked: core.selectedMonitor.muted === true
                onActivated: core.setMuted(core.selectedDisplayId, value)
            }

            Text {
                text: "Picture mode"
                color: Theme.text
                font.pixelSize: Theme.fontBase
                Layout.fillWidth: true
            }

            Flow {
                Layout.fillWidth: true
                visible: core.selectedMonitor.colorModeSupported === true
                spacing: 8

                Repeater {
                    model: core.pictureModes

                    Rectangle {
                        id: modeButton
                        required property var modelData
                        readonly property bool active: core.selectedMonitor.colorMode === modelData.value
                        width: modeText.implicitWidth + 26
                        height: 34
                        radius: Theme.radiusSmall
                        color: active ? Theme.accent : Theme.surfaceAlt
                        border.width: 1
                        border.color: active ? Theme.accent : Theme.border

                        Text {
                            id: modeText
                            anchors.centerIn: parent
                            text: modelData.label
                            color: modeButton.active ? "#ffffff" : Theme.text
                            font.pixelSize: Theme.fontBase
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: core.setColorMode(core.selectedDisplayId, modelData.value)
                        }
                    }
                }
            }

            Text {
                visible: core.selectedMonitor.colorModeSupported === true
                         && core.selectedMonitor.probed !== true
                text: "Reading the picture-mode list from the display\u2026"
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Text {
                visible: core.selectedMonitor.colorModeSupported !== true
                text: "This display does not report a picture-mode list (VCP 0xDC)."
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Text {
                visible: core.selectedMonitor.online !== true
                         && core.selectedMonitor.backlight !== true
                text: "This display is not answering DDC/CI, so brightness, volume and picture "
                      + "mode cannot be changed. Common causes:\n"
                      + "  • your user has no permission for /dev/i2c-*  (run the install script "
                      + "and log back in, or join the 'i2c' group);\n"
                      + "  • DDC/CI is disabled in the monitor's OSD menu;\n"
                      + "  • the connector does not carry a DDC channel.\n"
                      + (core.selectedMonitor.error
                         ? "\nLast error: " + core.selectedMonitor.error
                         : "")
                color: Theme.warn
                font.pixelSize: Theme.fontSmall
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        Card {
            title: "Panel information"
            Layout.fillWidth: true
            GridLayout {
                columns: 2
                columnSpacing: Theme.gap
                rowSpacing: 6
                Layout.fillWidth: true
                Text { text: "Connector"; color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                Text { text: core.selectedMonitor.connector || "-"; color: Theme.text; font.pixelSize: Theme.fontSmall }
                Text { text: "Serial"; color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                Text { text: core.selectedMonitor.serial || "-"; color: Theme.text; font.pixelSize: Theme.fontSmall }
                Text { text: "Physical size"; color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                Text {
                    text: core.selectedMonitor.widthMm
                          ? (core.selectedMonitor.widthMm + " x " + core.selectedMonitor.heightMm + " mm")
                          : "-"
                    color: Theme.text
                    font.pixelSize: Theme.fontSmall
                }
                Text { text: "Capabilities"; color: Theme.textDim; font.pixelSize: Theme.fontSmall }
                Text {
                    text: (core.selectedMonitor.capabilities || []).join(", ") || "-"
                    color: Theme.text
                    font.pixelSize: Theme.fontSmall
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }
        }

        Item { Layout.fillHeight: true; implicitHeight: 8 }
    }
}

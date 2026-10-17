pragma Singleton
import QtQuick

QtObject {
    id: theme

    property bool dark: false

    readonly property color bg:        dark ? "#14161a" : "#eef1f5"
    readonly property color surface:   dark ? "#1d2026" : "#ffffff"
    readonly property color surfaceAlt:dark ? "#252932" : "#f5f7fa"
    readonly property color text:      dark ? "#e8eaed" : "#1b1e22"
    readonly property color textDim:   dark ? "#98a1ad" : "#5b6470"
    readonly property color accent:    "#2f8f5b"
    readonly property color accentSoft:dark ? "#274a38" : "#d8ede1"
    readonly property color warn:      "#d9822b"
    readonly property color danger:    "#c0392b"
    readonly property color border:    dark ? "#2f343c" : "#e1e5eb"

    readonly property int radius: 12
    readonly property int radiusSmall: 8
    readonly property int pad: 16
    readonly property int gap: 12
    readonly property int fontSmall: 12
    readonly property int fontBase: 14
    readonly property int fontTitle: 18
    readonly property int fontHuge: 34
}

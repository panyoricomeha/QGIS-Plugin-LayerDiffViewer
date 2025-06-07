from qgis.PyQt.QtWidgets import QAction, QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtCore import QVariant, Qt

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsFields,
    QgsField, QgsSymbol, QgsRendererCategory, QgsCategorizedSymbolRenderer,
    QgsWkbTypes
)
import os

class LayerDiffViewer:
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icons", "icon.png")
        self.action = QAction(QIcon(icon_path), "Layer Difference Viewer", self.iface.mainWindow())
        self.action.triggered.connect(self.show_dialog)
        self.iface.addPluginToMenu("Layer Diff Viewer", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self.iface.removePluginMenu("Layer Diff Viewer", self.action)
        self.iface.removeToolBarIcon(self.action)

    def show_dialog(self):
        dlg = CompareDialog()
        dlg.exec_()


# --- GUI Dialog Class ---
class CompareDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Layer Comparison Dialog")
        self.setMinimumWidth(300)

        layout = QVBoxLayout()
        self.old_layer_cb = QComboBox()
        self.new_layer_cb = QComboBox()
        self.key_field_cb = QComboBox()
        self.compare_btn = QPushButton("Run Comparison")

        layout.addWidget(QLabel("Old Layer:"))
        layout.addWidget(self.old_layer_cb)
        layout.addWidget(QLabel("New Layer:"))
        layout.addWidget(self.new_layer_cb)
        layout.addWidget(QLabel("Key Field:"))
        layout.addWidget(self.key_field_cb)
        layout.addWidget(self.compare_btn)
        self.setLayout(layout)

        # Get vector layers
        layers = [l for l in QgsProject.instance().mapLayers().values() if isinstance(l, QgsVectorLayer)]
        self.layer_dict = {layer.name(): layer for layer in layers}

        self.old_layer_cb.addItems(self.layer_dict.keys())
        self.new_layer_cb.addItems(self.layer_dict.keys())

        self.old_layer_cb.currentTextChanged.connect(self.update_key_fields)
        self.new_layer_cb.currentTextChanged.connect(self.update_key_fields)
        self.compare_btn.clicked.connect(self.run_comparison)

        self.update_key_fields()

    def update_key_fields(self):
        self.key_field_cb.clear()
        name = self.new_layer_cb.currentText()
        layer = self.layer_dict.get(name)
        if layer:
            self.key_field_cb.addItems([f.name() for f in layer.fields()])

    def run_comparison(self):
        old_layer = self.layer_dict[self.old_layer_cb.currentText()]
        new_layer = self.layer_dict[self.new_layer_cb.currentText()]
        key_field = self.key_field_cb.currentText()
        self.close()
        compare_layers_with_visual_diff(old_layer, new_layer, key_field)


# --- Layer Comparison Logic ---
def compare_layers_with_visual_diff(old_layer, new_layer, key_field):
    old_features = {f[key_field]: f for f in old_layer.getFeatures()}
    new_features = {f[key_field]: f for f in new_layer.getFeatures()}

    field_names = [f.name() for f in new_layer.fields()]
    fields = QgsFields()
    for name in field_names:
        fields.append(QgsField(name, QVariant.String))
    fields.append(QgsField("change_type", QVariant.String))

    diff_features = []

    for key in old_features.keys() & new_features.keys():
        old_feat = old_features[key]
        new_feat = new_features[key]

        attr_changed = any(
            str(old_feat[name]) != str(new_feat[name])
            for name in field_names
        )
        geom_changed = not old_feat.geometry().equals(new_feat.geometry())

        if attr_changed and not geom_changed:
            change_type = "attr"
        elif not attr_changed and geom_changed:
            change_type = "geom"
        elif attr_changed and geom_changed:
            change_type = "attr"  # Or use "attr_geom"

        if attr_changed or geom_changed:
            f = QgsFeature()
            f.setGeometry(new_feat.geometry())
            f.setFields(fields)
            for name in field_names:
                f.setAttribute(name, new_feat[name])
            f.setAttribute("change_type", change_type)
            diff_features.append(f)

        if geom_changed:
            diff_geom = old_feat.geometry().symDifference(new_feat.geometry())
            diff_feat = QgsFeature()
            diff_feat.setGeometry(diff_geom)
            diff_feat.setFields(fields)
            for name in field_names:
                diff_feat.setAttribute(name, new_feat[name])
            diff_feat.setAttribute("change_type", "geom_diff")
            diff_features.append(diff_feat)

    for key in old_features.keys() - new_features.keys():
        old_feat = old_features[key]
        f = QgsFeature()
        f.setGeometry(old_feat.geometry())
        f.setFields(fields)
        for name in field_names:
            f.setAttribute(name, old_feat[name])
        f.setAttribute("change_type", "deleted")
        diff_features.append(f)

    for key in new_features.keys() - old_features.keys():
        new_feat = new_features[key]
        f = QgsFeature()
        f.setGeometry(new_feat.geometry())
        f.setFields(fields)
        for name in field_names:
            f.setAttribute(name, new_feat[name])
        f.setAttribute("change_type", "added")
        diff_features.append(f)

    geom_type = QgsWkbTypes.displayString(new_layer.wkbType())
    crs = new_layer.crs().authid()
    result_layer = QgsVectorLayer(f"{geom_type}?crs={crs}", "Layer Differences", "memory")
    result_layer.dataProvider().addAttributes(fields)
    result_layer.updateFields()
    result_layer.dataProvider().addFeatures(diff_features)

    def make_symbol(color_name, fill=True):
        symbol = QgsSymbol.defaultSymbol(result_layer.geometryType())
        symbol.setColor(QColor(color_name))
        if symbol.symbolLayerCount() > 0:
            symbol.symbolLayer(0).setStrokeColor(QColor(color_name))
            if result_layer.geometryType() == QgsWkbTypes.PolygonGeometry and not fill:
                symbol.symbolLayer(0).setBrushStyle(Qt.NoBrush)
        return symbol

    categories = [
        QgsRendererCategory("attr", make_symbol("blue"), "Attribute Changed"),
        QgsRendererCategory("geom", make_symbol("red"), "Geometry Changed"),
        QgsRendererCategory("geom_diff", make_symbol("orange", fill=False), "Geometry Difference"),
        QgsRendererCategory("added", make_symbol("green"), "Added"),
        QgsRendererCategory("deleted", make_symbol("gray"), "Deleted"),
    ]

    renderer = QgsCategorizedSymbolRenderer("change_type", categories)
    result_layer.setRenderer(renderer)

    QgsProject.instance().addMapLayer(result_layer)

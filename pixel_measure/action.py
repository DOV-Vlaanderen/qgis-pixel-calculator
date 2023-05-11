import PyQt5.QtGui as QtGui
import qgis.core as QGisCore

from .layer import PixelisedVectorLayer


class PixelMeasureAction(QtGui.QAction):
    """Class representing the action to start the pixel measure.
    Used as a menu item and toolbar button.
    """

    def __init__(self, main, parent):
        """Initialisation.
        Parameters
        ----------
        main : PixelCalculator
            Instance of main class.
        parent : QtGui.QWidget
            Widget used as parent widget for the action.
        """
        self.main = main
        self.iface = self.main.iface

        QtGui.QAction.__init__(self,
                               QtGui.QIcon(':/plugins/pixel_calculator/icon.png'),
                               'Bereken pixelwaarde',
                               parent)

        self.mapCanvas = self.main.iface.mapCanvas()
        self.mapCanvas.extentsChanged.connect(self._populateVisible)

        self.main.iface.currentLayerChanged.connect(self._populateApplicable)

        self.previousMapTool = None
        self.rasterLayer = None
        self.calculatedLayer = None
        self.layer = None
        self.activeLayer = None

        self._populateApplicable()

        self.setCheckable(True)
        self.triggered.connect(self.activate)

    def _populateApplicable(self):
        """Save the active layer, set the raster layer if applicable and call _populateVisible()."""
        self.active_layer = self.main.iface.activeLayer()
        if isinstance(self.active_layer, QGisCore.QgsRasterLayer):
            self.rasterLayer = self.active_layer
        else:
            self.rasterLayer = None
        self._populateVisible()

    def _populateVisible(self):
        """Enable or disable the action based on the visibility of the raster layer.
        Only show the action in the toolbar if the corresponding raster layer
        is visible too.
        """
        if self.layer is not None:
            self.setToolTip(self.main.tr('Berekening actief. Beëindig de huidige berekening.'))
            self.setEnabled(True)
        elif self.rasterLayer and \
            ((self.rasterLayer.hasScaleBasedVisibility() and
             self.rasterLayer.isInScaleRange(self.mapCanvas.scale())) or
                not self.rasterLayer.hasScaleBasedVisibility()):
            self.setToolTip(self.main.tr("Bereken pixelwaarde voor laag") + f" '{self.rasterLayer.name()}'.")
            self.setEnabled(True)
        elif self.rasterLayer and \
                (self.rasterLayer.hasScaleBasedVisibility()
                 and not self.rasterLayer.isInScaleRange(self.mapCanvas.scale())):
            self.setToolTip(self.main.tr(
                "De geselecteerde laag '{}' is niet zichtbaar op dit schaalniveau.").format(self.rasterLayer.name()))
            self.setEnabled(False)
        else:
            self.setToolTip(self.main.tr('Selecteer een rasterlaag om een berekening te kunnen starten.'))
            self.setEnabled(False)

    def activate(self, checked):
        """Activate or deactive the measurement action.
        Parameters
        ----------
        checked : boolean
            Current status of the toggle action. Start measurement if `True`,
            stop measurement if `False`.
        """
        if checked:
            self.startMeasure()
        else:
            self.stopMeasure()

    def startMeasure(self):
        """Start measuring.
        Add a PixelisedVectorLayer to the project and start drawing.
        """
        layer = PixelisedVectorLayer(self, rasterLayer=self.rasterLayer,
                                     path='Multipolygon?crs=epsg:31370',
                                     baseName=self.main.tr('Pixelberekening'),
                                     providerLib='memory')
        self.calculatedLayer = self.rasterLayer
        self.layer = QGisCore.QgsProject.instance().addMapLayer(layer, False)
        QGisCore.QgsProject.instance().layerTreeRoot().insertLayer(0, layer)
        self.main.iface.setActiveLayer(self.layer)
        self.main.iface.actionToggleEditing().trigger()
        self.main.iface.actionAddFeature().trigger()

    def stopMeasure(self):
        """Stop measuring.
        Remove memory layer from project.
        """
        self.setChecked(False)
        if self.layer:
            try:
                QGisCore.QgsProject.instance().removeMapLayer(
                    self.layer.id())
                self.main.iface.mapCanvas().refresh()
            except RuntimeError:
                pass
            self.layer = None

            self.main.iface.setActiveLayer(self.calculatedLayer)
            self.rasterLayer = None
            self.calculatedLayer = None
            self._populateApplicable()

    def deactivate(self):
        """Deactivate by disconnecting signals and stopping measurement."""
        self.triggered.disconnect(self.startMeasure)
        self.mapCanvas.extentsChanged.connect(self._populateVisible)
        self.stopMeasure()

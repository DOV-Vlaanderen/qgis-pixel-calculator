import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import qgis.core as QGisCore


class RasterBlockWrapper(QtCore.QObject):
    """Class to align a vector geometry to the grid of a raster layer."""

    def __init__(self, rasterLayer, band, geometry):
        """Initialisation.
        Aligns the given geometry to the grid of the raster layer.
        Parameters
        ----------
        rasterLayer : QGisCore.QgsRasterLayer
            The raster layer to use as the grid to align the geometry to.
        band : int
            The band of the rasterlayer to use to calculate summary statistics
            for the new geometry.
        geometry : QGisCore.QgsGeometry
            Geometry to align to the raster grid.
        """
        self.rasterLayer = rasterLayer
        self.band = band
        self.geometry = geometry
        self.geomBbox = self.geometry.boundingBox()

        self.pixelSizeX = self.rasterLayer.rasterUnitsPerPixelX()
        self.pixelSizeY = self.rasterLayer.rasterUnitsPerPixelY()
        self.pixelArea = self.pixelSizeX*self.pixelSizeY

        self._buffer = max(self.pixelSizeX, self.pixelSizeY)
        self.geomBbox = self.geomBbox.buffer(self._buffer)

        self.blockBbox = self._alignRectangleToGrid(self.geomBbox)
        self.blockWidth = int(self.blockBbox.width()/self.pixelSizeX)
        self.blockHeight = int(self.blockBbox.height()/self.pixelSizeY)
        self.block = self.rasterLayer.dataProvider().block(self.band,
                                                           self.blockBbox,
                                                           self.blockWidth,
                                                           self.blockHeight)

        self.newGeometry = None
        self.stats = {}

        self._process()

    def _alignRectangleToGrid(self, rect):
        """Aligns the given rectangle to the grid of the raster layer.
        Parameters
        ----------
        rect : QGisCore.QgsRectangle
            Rectangle to align.
        Returns
        -------
        QGisCore.QgsRectangle
            New rectangle, aligned to the grid of the raster layer.
        """
        rasterExtent = self.rasterLayer.extent()
        newRect = QGisCore.QgsRectangle()
        newRect.setXMinimum(rasterExtent.xMinimum() + (round(
            (rect.xMinimum()-rasterExtent.xMinimum()) / self.pixelSizeX) *
            self.pixelSizeX))
        newRect.setYMinimum(rasterExtent.yMinimum() + (round(
            (rect.yMinimum()-rasterExtent.yMinimum()) / self.pixelSizeY) *
            self.pixelSizeY))
        newRect.setXMaximum(newRect.xMinimum() + (int(
            rect.width()/self.pixelSizeX)*self.pixelSizeX))
        newRect.setYMaximum(newRect.yMinimum() + (int(
            rect.height()/self.pixelSizeY)*self.pixelSizeY))
        return newRect

    def _rasterCellMatchesGeometry(self, rect):
        """Check whether a given raster cell belongs to the geometry.
        In casu: a raster cell belongs to the geometry if at least 50 percent
        of the area of the raster cell falls inside the geometry.
        Parameters
        ----------
        rect : QGisCore.QgsRectangle
            The rectangle representing the raster cell.
        Returns
        -------
        boolean
            `True` if the raster cell belongs to the geometry, `False`
            otherwise.
        """
        # 50% overlap
        return self.geometry.intersection(
            QGisCore.QgsGeometry.fromRect(rect)).area() >= (self.pixelArea*0.5)

    def _process(self):
        """Calculate the new, aligned, geometry.
        Loop over all raster cells within the bounding box of the geometry and
        check for each of them if they should be part of the new geometry.
        Build a new QgsGeometry from the matching cells.
        Also builds a dictionary of statistics for the new QgsGeometry: listing
        the count, sum and average (mean) values of the raster cells it
        contains.
        """
        valSum = 0
        valCnt = 0

        noData = None
        if self.rasterLayer.dataProvider().srcHasNoDataValue(self.band):
            noData = self.rasterLayer.dataProvider().srcNoDataValue(self.band)

        for r in range(self.blockHeight):
            for c in range(self.blockWidth):
                cellRect = QGisCore.QgsRectangle()
                cellRect.setXMinimum(self.blockBbox.xMinimum() +
                                     (c*self.pixelSizeX))
                cellRect.setYMinimum(self.blockBbox.yMaximum() -
                                     (r*self.pixelSizeY)-self.pixelSizeY)
                cellRect.setXMaximum(self.blockBbox.xMinimum() +
                                     (c*self.pixelSizeX)+self.pixelSizeX)
                cellRect.setYMaximum(self.blockBbox.yMaximum() -
                                     (r*self.pixelSizeY))
                if self._rasterCellMatchesGeometry(cellRect):
                    value = self.block.value(r, c)

                    if noData and value == noData:
                        continue

                    valSum += self.block.value(r, c)
                    valCnt += 1
                    if not self.newGeometry:
                        self.newGeometry = QGisCore.QgsGeometry.fromRect(
                            cellRect)
                    else:
                        self.newGeometry = self.newGeometry.combine(
                            QGisCore.QgsGeometry.fromRect(cellRect))

        if valCnt > 0:
            self.stats.clear()
            self.stats['sum'] = valSum
            self.stats['count'] = valCnt
            self.stats['avg'] = valSum/float(valCnt)

    def getRasterizedGeometry(self):
        """Get the rasterized, aligned, version of the input geometry.
        Returns
        -------
        QGisCore.QgsGeometry
            Aligned version of the input geometry.
        """
        return self.newGeometry

    def getStats(self):
        """Get the summary statistics of the raster cells of the new geometry.
        Returns
        -------
        dict
            Dictionary containing the summary statistics, with values for
            'count', 'sum' and 'avg'.
        """
        return self.stats

    def isEmpty(self):
        """Check if the aligned geometry is available.
        Returns
        -------
        boolean
            `True` if the new geometry is available, `False` otherwise.
        """
        return self.newGeometry is None


class PixelisedVectorLayer(QGisCore.QgsVectorLayer):
    """Class representing a pixelised polygon layer.
    This is a polygon layer that aligns features drawn onto it to the grid of
    a given raster layer. The border of all vector features overlap with the
    border of the grid cells of the rasterlayer.
    """

    def __init__(self, main, rasterLayer, path=None, baseName=None,
                 providerLib=None, loadDefaultStyleFlag=True):
        """Initialisation.
        Parameters
        ----------
        main : erosiebezwaren.Erosiebezwaren
            Instance of main class.
        rasterLayer : QGisCore.QgsRasterLayer
            Rasterlayer to use as the reference grid.
        path : str, optional
            The path or url of the parameter. Typically this encodes parameters
            used by the data provider as url query items.
        baseName : str, optional
            The name used to represent the layer in the legend.
        providerLib : str, optional
            The name of the data provider, eg "memory", "postgres".
        loadDefaultStyleFlag : boolean, optional, default `True`
            Whether to load the default style.
        """
        QGisCore.QgsVectorLayer.__init__(self, path, baseName, providerLib,
                                         loadDefaultStyleFlag)
        self.rasterLayer = rasterLayer
        self.main = main

        props = self.rendererV2().symbol().symbolLayer(0).properties()
        props['color'] = '255,255,255,64'
        props['outline_color'] = '0,0,0,255'
        props['outline_width'] = '1'
        self.rendererV2().setSymbol(
            QGisCore.QgsFillSymbolV2.createSimple(props))

        self.setCustomProperty("labeling", "pal")
        self.setCustomProperty("labeling/isExpression", True)
        self.setCustomProperty("labeling/enabled", True)
        self.setCustomProperty("labeling/fontSize", "12")
        self.setCustomProperty("labeling/fontWeight", "75")
        self.setCustomProperty("labeling/displayAll", True)
        self.setCustomProperty("labeling/bufferColorA", 255)
        self.setCustomProperty("labeling/bufferColorR", 255)
        self.setCustomProperty("labeling/bufferColorG", 255)
        self.setCustomProperty("labeling/bufferColorB", 255)
        self.setCustomProperty("labeling/bufferSize", "1.5")

        QtCore.QObject.connect(self, QtCore.SIGNAL('editingStarted()'),
                               self._cb_editingStarted)
        QtCore.QObject.connect(self, QtCore.SIGNAL('beforeCommitChanges()'),
                               self._cb_beforeCommitChanges)

    def _cb_editingStarted(self):
        """Connect the featureAdded signal.
        Callback for the 'editingStarted' event.
        """
        QtCore.QObject.connect(self.editBuffer(),
                               QtCore.SIGNAL('featureAdded(QgsFeatureId)'),
                               self._cb_featureAdded)

    def _cb_beforeCommitChanges(self):
        """Disconnect the featureAdded signal.
        Callback for the 'beforeCommitChanges' event.
        """
        QtCore.QObject.disconnect(self.editBuffer(),
                                  QtCore.SIGNAL('featureAdded(QgsFeatureId)'),
                                  self._cb_featureAdded)

    def _cb_featureAdded(self, fid):
        """Pixelise the feature drawn.
        Align the polygon to the raster grid by creating a RasterBlockWrapper
        and updating the geometry of the feature. Also add the average
        (arithmetic mean) value of the cells of the newly created geometry as
        a label.
        Parameters
        ----------
        fid : int
            Feature id of the added feature.
        """
        ft = self.getFeatures(QGisCore.QgsFeatureRequest(fid)).next()
        block = RasterBlockWrapper(self.rasterLayer, 1, ft.geometry())

        if not block.isEmpty():
            self.changeGeometry(fid, block.getRasterizedGeometry())
            self.setCustomProperty("labeling/fieldName", "%0.2f" %
                                   block.getStats()['avg'])
        else:
            self.editBuffer().deleteFeature(fid)

        self.commitChanges()


class PixelMeasureAction(QtGui.QAction):
    """Class representing the action to start the pixel measure.
    Used as a toolbar button.
    """

    def __init__(self, main, parent, rasterLayerName):
        """Initialisation.
        Parameters
        ----------
        main : erosiebezwaren.Erosiebezwaren
            Instance of main class.
        parent : QtGui.QWidget
            Widget used as parent widget for the action.
        rasterLayerName : str
            Name of the raster layer in the project to measure.
        """
        self.main = main
        self.rasterLayerName = rasterLayerName
        QtGui.QAction.__init__(self,
                               QtGui.QIcon(':/icons/icons/pixelmeasure.png'),
                               'Bereken pixelwaarden',
                               parent)

        self.mapCanvas = self.main.iface.mapCanvas()
        QtCore.QObject.connect(self.mapCanvas,
                               QtCore.SIGNAL('extentsChanged()'),
                               self.populateVisible)

        self.rasterLayer = self.main.utils.getLayerByName(self.rasterLayerName)
        self.rasterLayerActive = False
        self.previousMapTool = None
        self.layer = None

        self.setCheckable(True)
        QtCore.QObject.connect(self, QtCore.SIGNAL('triggered(bool)'),
                               self.activate)

    def populateVisible(self):
        """Show or hide the action based on the visibility of the raster layer.
        Only show the action in the toolbar if the corresponding raster layer
        is visible too.
        """
        if not self.rasterLayer:
            self.rasterLayer = self.main.utils.getLayerByName(
                self.rasterLayerName)

        if self.rasterLayer and self.rasterLayerActive and \
            ((self.rasterLayer.hasScaleBasedVisibility() and
              self.rasterLayer.minimumScale() <= self.mapCanvas.scale() <
              self.rasterLayer.maximumScale()) or
             (not self.rasterLayer.hasScaleBasedVisibility())):
            self.setVisible(True)
        else:
            self.setVisible(False)

    def setRasterLayerActive(self, active):
        """Set the visibility status of the raster layer.
        Controls the visibility of this Action accordingly by calling
        populate(). This should ideally be set by handling the appropriate
        event of the legend panel.
        Parameters
        ----------
        active : boolean
            The new status of the raster layer.
        """
        self.rasterLayerActive = active
        self.populateVisible()

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
        layer = PixelisedVectorLayer(self.main, rasterLayer=self.rasterLayer,
                                     path='Multipolygon?crs=epsg:31370',
                                     baseName='Pixelberekening',
                                     providerLib='memory')
        self.layer = QGisCore.QgsMapLayerRegistry.instance().addMapLayer(
            layer, False)
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
                QGisCore.QgsMapLayerRegistry.instance().removeMapLayer(
                    self.layer.id())
            except RuntimeError:
                pass
            self.layer = None

    def deactivate(self):
        """Deactivate by disconnecting signals and stopping measurement."""
        QtCore.QObject.disconnect(
            self, QtCore.SIGNAL('triggered(bool)'), self.startMeasure)
        QtCore.QObject.connect(
            self.mapCanvas, QtCore.SIGNAL('extentsChanged()'),
            self.populateVisible)
        self.stopMeasure()

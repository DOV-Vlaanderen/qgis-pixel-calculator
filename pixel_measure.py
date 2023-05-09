import PyQt5.QtCore as QtCore
import PyQt5.QtGui as QtGui
import qgis.core as QGisCore


class RasterBlockWrapper(QGisCore.QgsTask):
    """Class to align a vector geometry to the grid of a raster layer."""

    taskFinished = QtCore.pyqtSignal(object)

    def __init__(self, rasterLayer, band, geometry, callback):
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
        super().__init__('Pixelwaarde berekenen', QGisCore.QgsTask.CanCancel)
        self.setDependentLayers([rasterLayer])

        self.rasterLayer = rasterLayer
        self.band = band
        self.geometry = geometry
        self.callback = callback

        self.geomBbox = self.geometry.boundingBox()

        self.pixelSizeX = self.rasterLayer.rasterUnitsPerPixelX()
        self.pixelSizeY = self.rasterLayer.rasterUnitsPerPixelY()
        self.pixelArea = self.pixelSizeX*self.pixelSizeY

        self._buffer = max(self.pixelSizeX, self.pixelSizeY)
        self.geomBbox = self.geomBbox.buffered(self._buffer)

        self.blockBbox = self._alignRectangleToGrid(self.geomBbox)
        self.blockWidth = int(self.blockBbox.width()/self.pixelSizeX)
        self.blockHeight = int(self.blockBbox.height()/self.pixelSizeY)
        self.block = self.rasterLayer.dataProvider().block(self.band,
                                                           self.blockBbox,
                                                           self.blockWidth,
                                                           self.blockHeight)

        self.stats = {}
        self.newGeometry = None

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

    def run(self):
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

        progress_done = 0
        progress_todo = self.blockWidth * self.blockHeight

        noData = None
        if self.rasterLayer.dataProvider().sourceHasNoDataValue(self.band):
            noData = self.rasterLayer.dataProvider().sourceNoDataValue(self.band)

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

                progress_done += 1
                self.setProgress((progress_done/progress_todo) * 100)

        if valCnt > 0:
            self.stats['sum'] = valSum
            self.stats['count'] = valCnt
            self.stats['avg'] = valSum/float(valCnt)

        self.taskFinished.emit((self.newGeometry, self.stats))
        return True


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
                                         QGisCore.QgsVectorLayer.LayerOptions(
                                             loadDefaultStyleFlag, readExtentFromXml=False))
        self.rasterLayer = rasterLayer
        self.main = main

        self._set_scaleBasedVisibility()
        self._set_labeling()

        self.editingStarted.connect(self._cb_editingStarted)
        self.beforeCommitChanges.connect(self._cb_beforeCommitChanges)

    def _set_scaleBasedVisibility(self):
        if self.rasterLayer.hasScaleBasedVisibility():
            self.setScaleBasedVisibility(True)
            self.setMinimumScale(self.rasterLayer.minimumScale())
            self.setMaximumScale(self.rasterLayer.maximumScale())
        else:
            self.setScaleBasedVisibility(False)

    def _set_labeling(self):
        props = self.renderer().symbol().symbolLayer(0).properties()
        props['color'] = '255,255,255,64'
        props['outline_color'] = '0,0,0,255'
        props['outline_width'] = '1'
        self.renderer().setSymbol(
            QGisCore.QgsFillSymbol.createSimple(props))

        label_settings = QGisCore.QgsPalLayerSettings()
        label_settings.enabled = True
        label_settings.placement = QGisCore.QgsPalLayerSettings.AroundPoint

        label_format = QGisCore.QgsTextFormat()
        label_format.setSize(12)
        label_format.setForcedBold(True)
        label_format.setColor(QtGui.QColor(0, 0, 0, 255))

        label_buffer = QGisCore.QgsTextBufferSettings()
        label_buffer.setEnabled(True)
        label_buffer.setSize(1.5)
        label_buffer.setColor(QtGui.QColor(255, 255, 255, 255))
        label_format.setBuffer(
            label_buffer
        )
        label_settings.setFormat(
            label_format
        )

        self.setLabeling(QGisCore.QgsVectorLayerSimpleLabeling(label_settings))
        self.setLabelsEnabled(True)

    def _cb_editingStarted(self):
        """Connect the featureAdded signal.
        Callback for the 'editingStarted' event.
        """
        self.editBuffer().featureAdded.connect(self._cb_featureAdded)

    def _cb_beforeCommitChanges(self):
        """Disconnect the featureAdded signal.
        Callback for the 'beforeCommitChanges' event.
        """
        self.editBuffer().featureAdded.disconnect(self._cb_featureAdded)

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
        def drawPixelisedFeature(result):
            geometry, stats = result
            if geometry is not None:
                self.changeGeometry(fid, geometry)

                label_settings = self.labeling().settings()
                label_settings.fieldName = "%0.2f" % stats['avg']
                label_settings.isExpression = True

                self.labeling().setSettings(label_settings)
                self.triggerRepaint()
            else:
                self.editBuffer().deleteFeature(fid)

            self.commitChanges()

        ft = next(self.getFeatures(QGisCore.QgsFeatureRequest(fid)))

        task = RasterBlockWrapper(self.rasterLayer, 1, ft.geometry(), drawPixelisedFeature)
        task.taskFinished.connect(drawPixelisedFeature)
        QGisCore.QgsApplication.taskManager().addTask(task)


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
        QtGui.QAction.__init__(self,
                               QtGui.QIcon(':/plugins/pixel_calculator/icon.png'),
                               'Bereken pixelwaarden',
                               parent)

        self.mapCanvas = self.main.iface.mapCanvas()
        self.mapCanvas.extentsChanged.connect(self.populateVisible)

        self.main.iface.currentLayerChanged.connect(self.populateApplicable)

        self.rasterLayer = None
        self.previousMapTool = None
        self.layer = None

        self.populateApplicable()

        self.setCheckable(True)
        self.triggered.connect(self.activate)

    def populateApplicable(self):
        active_layer = self.main.iface.activeLayer()
        if isinstance(active_layer, QGisCore.QgsRasterLayer) or active_layer == self.layer:
            self.rasterLayer = active_layer
        else:
            self.rasterLayer = None
        self.populateVisible()

    def populateVisible(self):
        """Show or hide the action based on the visibility of the raster layer.
        Only show the action in the toolbar if the corresponding raster layer
        is visible too.
        """
        if self.rasterLayer and \
            ((self.rasterLayer.hasScaleBasedVisibility() and
             self.rasterLayer.isInScaleRange(self.mapCanvas.scale())) or
                not self.rasterLayer.hasScaleBasedVisibility()):
            self.setEnabled(True)
        else:
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
        layer = PixelisedVectorLayer(self.main, rasterLayer=self.rasterLayer,
                                     path='Multipolygon?crs=epsg:31370',
                                     baseName='Pixelberekening',
                                     providerLib='memory')
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

    def deactivate(self):
        """Deactivate by disconnecting signals and stopping measurement."""
        self.triggered.disconnect(self.startMeasure)
        self.mapCanvas.extentsChanged.connect(self.populateVisible)
        self.stopMeasure()

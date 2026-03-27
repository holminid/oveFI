#!/usr/bin/env python3
"""analysis.plugins

Plugin system for the analysis pipeline providing extensible hooks for
data transformation and feature extraction.

Plugins can be wrapped around various parts of the analysis workflow:
- In analysis.pipeline.Pipeline.run() around the main processing loop
- Around analysis.pipeline.extract_features() for feature extraction
- Around sentiment analysis functions in analysis/features/text.py (when implemented)
- In script entrypoints that process datasets

Example usage:
    plugin = NoOpPlugin()
    plugin.fit(dataset)  # Optional training/setup phase
    processed_item = plugin.transform(item)  # Transform individual items
"""
from __future__ import annotations

import abc
from typing import Any, Iterable, Optional

__all__ = ["Plugin", "PluginFit", "PluginTransform", "NoOpPlugin"]


class Plugin:
    """Base class for analysis pipeline plugins.
    
    Provides optional lifecycle methods for plugins that need to fit to data
    or transform individual items during processing.
    """

    def fit(self, data: Optional[Iterable[Any]] = None) -> None:
        """Optional training/setup phase that receives the full dataset.
        
        Args:
            data: Optional iterable of data items for training/setup.
                  Can be None if no training data is available.
        
        Default implementation does nothing.
        """
        pass

    def transform(self, item: Any) -> Any:
        """Transform a single data item during processing.
        
        Args:
            item: The data item to transform.
            
        Returns:
            The transformed item (may be the original item unchanged).
            
        Default implementation returns the item unchanged.
        """
        return item


class PluginFit(Plugin, abc.ABC):
    """Marker class for plugins that require a fit method implementation.
    
    Subclasses must implement the fit method.
    """

    @abc.abstractmethod
    def fit(self, data: Optional[Iterable[Any]] = None) -> None:
        """Must implement training/setup phase."""
        pass


class PluginTransform(Plugin, abc.ABC):
    """Marker class for plugins that require a transform method implementation.
    
    Subclasses must implement the transform method.
    """

    @abc.abstractmethod
    def transform(self, item: Any) -> Any:
        """Must implement item transformation."""
        pass


class NoOpPlugin(Plugin):
    """No-operation plugin that implements both methods as no-ops.
    
    Useful as a default plugin or for testing plugin integration points.
    """

    def fit(self, data: Optional[Iterable[Any]] = None) -> None:
        """No-op fit implementation - does nothing."""
        pass

    def transform(self, item: Any) -> Any:
        """No-op transform implementation - returns input unchanged."""
        return item
"""
Elementary measurement acquisitions.
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MeasurementResult:
    """Container for measurement results."""

    timestamp: datetime
    integration_time: float

    # Spectral data
    wavelengths: Optional[np.ndarray] = None
    intensities: Optional[np.ndarray] = None
    background: Optional[np.ndarray] = None
    background_exposure: Optional[float] = None # In seconds

    # Imaging data
    image: Optional[np.ndarray] = None

    # Power monitoring
    measured_power: Optional[float] = None

    # Position
    position: Optional[tuple] = None

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def has_spectrum(self) -> bool:
        """Check if result contains spectral data."""
        return self.wavelengths is not None and self.intensities is not None

    def has_image(self) -> bool:
        """Check if result contains image data."""
        return self.image is not None

    def process(self, mode: str) -> 'MeasurementResult':
        """
        Apply processing (Background correction, Time Normalization) to intensities.
        Modifies intensities in-place and updates metadata.
        
        Args:
            mode: one of "Raw Data", "Background correction", 
                  "Time Normalized", "Background & Time Normalized"
        """
        if self.intensities is None:
            return self
            
        data = self.intensities.astype(np.float64)
        applied = []
        
        # 1. Background Subtraction
        if "Background" in mode and self.background is not None:
            # Check for exposure mismatch (tolerance: 0.1ms)
            if self.background_exposure is not None and abs(self.integration_time - self.background_exposure) > 1e-4:
                logger.warning(f"Background exposure mismatch: data {self.integration_time*1000:.1f}ms vs bg {self.background_exposure*1000:.1f}ms. Skipping.")
                applied.append("Background (Skipped - Exposure Mismatch)")
            # Match shapes
            elif data.shape == self.background.shape:
                data = data - self.background.astype(np.float64)
                applied.append("Background Subtracted")
            elif self.background.ndim == 2 and data.ndim == 1:
                # Collapse 2D background to 1D
                bg_spec = np.sum(self.background, axis=0)
                if bg_spec.shape == data.shape:
                    # Heuristic: If background total is > 100x the raw data, 
                    # it might be a vertical ROI mismatch (e.g. full sensor BG vs narrow track)
                    bg_mean = np.mean(bg_spec)
                    data_mean = np.mean(data)
                    if bg_mean > data_mean * 100 and data_mean > 0:
                        logger.warning(f"Background magnitude ({bg_mean:.1f}) is much larger than data ({data_mean:.1f}). Skipping subtraction to avoid negative signal.")
                        applied.append("Background (Skipped - Magnitude Mismatch)")
                    else:
                        data = data - bg_spec.astype(np.float64)
                        applied.append("Background Subtracted (Collapsed)")
        
        # 2. Time Normalization
        if "Time Normalized" in mode:
            if self.integration_time > 0:
                data = data / self.integration_time
                applied.append(f"Time Normalized (/{self.integration_time}s)")
        
        self.intensities = data
        if applied:
            self.metadata['Processing'] = " + ".join(applied)
        else:
            self.metadata['Processing'] = "Raw"
            
        return self


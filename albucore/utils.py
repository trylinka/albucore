from __future__ import annotations

import sys
from functools import wraps
from typing import Any, Callable, Literal, Union, cast

if sys.version_info >= (3, 10):
    from typing import Concatenate, ParamSpec
else:
    from typing_extensions import Concatenate, ParamSpec

import cv2
import numpy as np

NUM_RGB_CHANNELS = 3
FOUR = 4
TWO = 2

MAX_OPENCV_WORKING_CHANNELS = 4

NormalizationType = Literal["image", "image_per_channel", "min_max", "min_max_per_channel"]

P = ParamSpec("P")

MAX_VALUES_BY_DTYPE = {
    np.dtype("uint8"): 255,
    np.dtype("uint16"): 65535,
    np.dtype("uint32"): 4294967295,
    np.dtype("float16"): 1.0,
    np.dtype("float32"): 1.0,
    np.dtype("float64"): 1.0,
    np.uint8: 255,
    np.uint16: 65535,
    np.uint32: 4294967295,
    np.float16: 1.0,
    np.float32: 1.0,
    np.float64: 1.0,
    np.int32: 2147483647,
}

NPDTYPE_TO_OPENCV_DTYPE = {
    np.uint8: cv2.CV_8U,
    np.uint16: cv2.CV_16U,
    np.float32: cv2.CV_32F,
    np.float64: cv2.CV_64F,
    np.int32: cv2.CV_32S,
    np.dtype("uint8"): cv2.CV_8U,
    np.dtype("uint16"): cv2.CV_16U,
    np.dtype("float32"): cv2.CV_32F,
    np.dtype("float64"): cv2.CV_64F,
    np.dtype("int32"): cv2.CV_32S,
}


def maybe_process_in_chunks(
    process_fn: Callable[Concatenate[np.ndarray, P], np.ndarray],
    *args: P.args,
    **kwargs: P.kwargs,
) -> Callable[[np.ndarray], np.ndarray]:
    """Wrap OpenCV function to enable processing images with more than 4 channels.

    Limitations:
        This wrapper requires image to be the first argument and rest must be sent via named arguments.

    Args:
        process_fn: Transform function (e.g cv2.resize).
        args: Additional positional arguments.
        kwargs: Additional keyword arguments.

    Returns:
        np.ndarray: Transformed image.
    """

    @wraps(process_fn)
    def __process_fn(img: np.ndarray, *process_args: P.args, **process_kwargs: P.kwargs) -> np.ndarray:
        # Merge args and kwargs
        all_args = (*args, *process_args)
        all_kwargs: dict[str, Any] = kwargs | process_kwargs

        num_channels = img.shape[-1]
        if num_channels > MAX_OPENCV_WORKING_CHANNELS:
            chunks = []
            for index in range(0, num_channels, 4):
                if num_channels - index == TWO:
                    # Many OpenCV functions cannot work with 2-channel images
                    for i in range(2):
                        chunk = img[:, :, index + i : index + i + 1]
                        chunk = process_fn(chunk, *all_args, **all_kwargs)
                        chunk = np.expand_dims(chunk, -1)
                        chunks.append(chunk)
                else:
                    chunk = img[:, :, index : index + 4]
                    chunk = process_fn(chunk, *all_args, **all_kwargs)
                    chunks.append(chunk)
            return np.dstack(chunks)

        return process_fn(img, *all_args, **all_kwargs)

    return __process_fn


def clip(img: np.ndarray, dtype: Any, inplace: bool = False) -> np.ndarray:
    max_value = MAX_VALUES_BY_DTYPE[dtype]
    if inplace and img.dtype == dtype:
        return np.clip(img, 0, max_value, out=img).astype(dtype, copy=False)
    return np.clip(img, 0, max_value).astype(dtype, copy=False)


def clipped(func: Callable[Concatenate[np.ndarray, P], np.ndarray]) -> Callable[Concatenate[np.ndarray, P], np.ndarray]:
    @wraps(func)
    def wrapped_function(img: np.ndarray, *args: P.args, **kwargs: P.kwargs) -> np.ndarray:
        dtype = img.dtype
        result = func(img, *args, **kwargs)

        if result.dtype == np.uint8:
            return result

        return clip(result, dtype)

    return wrapped_function


def get_num_channels(image: np.ndarray) -> int:
    """Get the number of channels in an image array.

    This function returns the size of the last dimension, which always represents
    the number of channels in our convention.

    Args:
        image: Input image array. Expected shapes:
            - HWC: (height, width, channels) - multi-channel image
            - NHWC: (batch, height, width, channels) - batch of multi-channel images
            - DHWC: (depth, height, width, channels) - 3D multi-channel volume
            - NDHWC: (batch, depth, height, width, channels) - batch of 3D multi-channel volumes

    Returns:
        int: Number of channels (the size of the last dimension).

    Examples:
        >>> # Grayscale image with explicit channel
        >>> img = np.zeros((100, 200, 1))
        >>> get_num_channels(img)
        1

        >>> # RGB image
        >>> img = np.zeros((100, 200, 3))
        >>> get_num_channels(img)
        3

        >>> # Batch of grayscale images
        >>> img = np.zeros((10, 100, 200, 1))
        >>> get_num_channels(img)
        1

        >>> # Batch of RGB images
        >>> img = np.zeros((10, 100, 200, 3))
        >>> get_num_channels(img)
        3

        >>> # 3D grayscale volume
        >>> img = np.zeros((5, 100, 200, 1))
        >>> get_num_channels(img)
        1

        >>> # Batch of 3D volumes with RGB
        >>> img = np.zeros((5, 10, 100, 200, 3))
        >>> get_num_channels(img)
        3

    Note:
        Since we always expect the channel dimension to be present (even for grayscale
        images which have shape[..., 1]), this function simply returns shape[-1].
    """
    return int(image.shape[-1])


def is_grayscale_image(image: np.ndarray) -> bool:
    """Check if an image array represents a grayscale (single-channel) image.

    This function determines whether an image has only one channel by checking if
    shape[-1] == 1.

    Args:
        image: Input image array with explicit channel dimension.

    Returns:
        bool: True if the image has only 1 channel (shape[-1] == 1), False otherwise.

    Examples:
        >>> # Grayscale image with explicit channel
        >>> img = np.zeros((100, 200, 1))
        >>> is_grayscale_image(img)
        True

        >>> # RGB image
        >>> img = np.zeros((100, 200, 3))
        >>> is_grayscale_image(img)
        False

        >>> # Batch of grayscale images
        >>> img = np.zeros((10, 100, 200, 1))
        >>> is_grayscale_image(img)
        True

        >>> # Batch of RGB images
        >>> img = np.zeros((10, 100, 200, 3))
        >>> is_grayscale_image(img)
        False

    See Also:
        get_num_channels: For getting the exact number of channels.
        is_rgb_image: For checking if an image has exactly 3 channels (RGB).
        is_multispectral_image: For checking if an image has channels other than 1 or 3.
    """
    return cast("bool", image.shape[-1] == 1)


def get_opencv_dtype_from_numpy(value: np.ndarray | int | np.dtype | object) -> int:
    if isinstance(value, np.ndarray):
        value = value.dtype
    return int(NPDTYPE_TO_OPENCV_DTYPE[value])


def is_rgb_image(image: np.ndarray) -> bool:
    return cast("bool", image.shape[-1] == NUM_RGB_CHANNELS)


def is_multispectral_image(image: np.ndarray) -> bool:
    return image.shape[-1] not in {1, 3}


def convert_value(value: np.ndarray | float, num_channels: int) -> float | np.ndarray:
    """Convert a value to a float or numpy array based on its shape and number of channels.

    Args:
        value: Input value to convert (numpy array, float, or int)
        num_channels: Number of channels in the target image

    Returns:
        float: If value is a scalar or 1D array that should be converted to scalar
        np.ndarray: If value is a multi-dimensional array or channel vector

    Raises:
        TypeError: If value is of unsupported type
    """
    # Handle scalar types
    if isinstance(value, (float, int, np.float32, np.float64)):
        return float(value) if isinstance(value, (float, int)) else value.item()

    # Handle numpy arrays
    if isinstance(value, np.ndarray):  # type: ignore[unreachable]
        # Return scalars and 0-dim arrays as float
        if value.ndim == 0:
            return value.item()

        # Return multi-dimensional arrays as-is
        if value.ndim > 1:
            return value

        # Handle 1D arrays
        if len(value) == 1 or num_channels == 1 or len(value) < num_channels:
            return float(value[0])

        return value[:num_channels]

    raise TypeError(f"Unsupported value type: {type(value)}")


ValueType = Union[np.ndarray, float, int]


def get_max_value(dtype: np.dtype) -> float:
    if dtype not in MAX_VALUES_BY_DTYPE:
        msg = (
            f"Can't infer the maximum value for dtype {dtype}. "
            "You need to specify the maximum value manually by passing the max_value argument."
        )
        raise RuntimeError(msg)
    return MAX_VALUES_BY_DTYPE[dtype]


def get_image_data(data: dict[str, Any]) -> dict[str, np.dtype | int]:
    """Extract image metadata (dtype, height, width, num_channels) from a dictionary.

    This function checks for image data under specific keys in priority order:
    'image' > 'images' > 'volume' > 'volumes'

    The function correctly extracts height and width by accounting for batch
    and depth dimensions based on the key type:
    - 'image': Direct H, W from shape[0], shape[1]
    - 'images': Skip batch dimension (shape[1], shape[2])
    - 'volume': Skip depth dimension (shape[1], shape[2])
    - 'volumes': Skip batch and depth dimensions (shape[2], shape[3])

    Args:
        data: Dictionary potentially containing image/volume arrays under specific keys.

    Returns:
        dict: Dictionary with 'dtype', 'height', 'width', and 'num_channels' keys.

    Raises:
        ValueError: If no valid image/volume data keys are found in the dictionary.
    """
    if "image" in data:
        shape = data["image"].shape
        return {
            "dtype": data["image"].dtype,
            "height": shape[0],
            "width": shape[1],
            "num_channels": shape[-1],
        }
    if "images" in data:
        shape = data["images"].shape
        return {
            "dtype": data["images"].dtype,
            "height": shape[1],
            "width": shape[2],
            "num_channels": shape[-1],
        }
    if "volume" in data:
        shape = data["volume"].shape
        return {
            "dtype": data["volume"].dtype,
            "height": shape[1],
            "width": shape[2],
            "num_channels": shape[-1],
        }
    if "volumes" in data:
        shape = data["volumes"].shape
        return {
            "dtype": data["volumes"].dtype,
            "height": shape[2],
            "width": shape[3],
            "num_channels": shape[-1],
        }
    raise ValueError("No valid image/volume data found in data dict")

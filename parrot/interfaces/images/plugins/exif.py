from collections.abc import Mapping, Sequence
from typing import Any, Dict, Optional
import re
import struct
from io import BytesIO
from PIL import Image, ExifTags
from PIL.ExifTags import TAGS, GPSTAGS, IFD
from PIL import TiffImagePlugin
from PIL.TiffImagePlugin import IFDRational
from pillow_heif import register_heif_opener
from .abstract import ImagePlugin


register_heif_opener()  # ADD HEIF support


def _json_safe(obj):
    """Return a structure containing only JSON‑serialisable scalar types,
    no IFDRational, no bytes, and **no NUL characters**."""
    if isinstance(obj, IFDRational):
        return float(obj)

    if isinstance(obj, bytes):
        # bytes -> str *and* strip embedded NULs
        return obj.decode(errors="replace").replace('\x00', '')

    if isinstance(obj, str):
        # Remove NUL chars from normal strings too
        return obj.replace('\x00', '')

    if isinstance(obj, Mapping):
        return {k: _json_safe(v) for k, v in obj.items()}

    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [_json_safe(v) for v in obj]

    return obj


def _make_serialisable(val):
    if isinstance(val, IFDRational):
        return float(val)
    if isinstance(val, bytes):
        return val.decode(errors="replace")
    return val


class EXIFPlugin(ImagePlugin):
    """
    EXIFPlugin is a plugin for extracting EXIF data from images.
    It extends the ImagePlugin class and implements the analyze method to extract EXIF data.
    """
    column_name: str = "exif_data"

    def __init__(self, *args, **kwargs):
        self.extract_geoloc: bool = kwargs.get("extract_geoloc", False)
        super().__init__(*args, **kwargs)

    def convert_to_degrees(self, value):
        """
        Convert GPS coordinates to degrees with proper error handling.
        """
        try:
            # Handles case where value is tuple of Rational objects
            def to_float(r):
                if hasattr(r, "num") and hasattr(r, "den"):
                    # Prevent division by zero
                    if r.den == 0:
                        return 0.0
                    return float(r.num) / float(r.den)
                else:
                    # Handle non-rational values
                    return float(r) if r is not None else 0.0

            # Ensure all three components exist
            if len(value) < 3 or None in value:
                self.logger.warning(f"Invalid GPS value format: {value}")
                return None

            d = to_float(value[0])
            m = to_float(value[1])
            s = to_float(value[2])

            return d + (m / 60.0) + (s / 3600.0)
        except Exception as e:
            self.logger.debug(f"Error converting GPS value to degrees: {e}")
            return None

    def extract_gps_datetime(self, exif: dict):
        """
        Extract GPS coordinates and datetime from EXIF data with improved error handling.
        """
        gps = exif.get("GPSInfo", {})
        datetime = exif.get("DateTimeOriginal") or exif.get("DateTime")

        latitude = longitude = None

        if gps:
            lat = gps.get("GPSLatitude")
            lat_ref = gps.get("GPSLatitudeRef")
            lon = gps.get("GPSLongitude")
            lon_ref = gps.get("GPSLongitudeRef")

            if lat and lat_ref and lon and lon_ref:
                # Convert coordinates to degrees
                latitude = self.convert_to_degrees(lat)
                longitude = self.convert_to_degrees(lon)

                # Apply reference direction only if conversion succeeded
                if latitude is not None and lat_ref == "S":
                    latitude = -latitude

                if longitude is not None and lon_ref == "W":
                    longitude = -longitude

        return {
            "datetime": datetime,
            "latitude": latitude,
            "longitude": longitude
        }

    def _extract_apple_gps_from_mime(self, mime_data: bytes, exif_data: Dict) -> None:
        """
        Extract GPS data from Apple's MIME metadata in HEIF files.

        Args:
            mime_data: MIME metadata bytes
            exif_data: Dictionary to update with GPS data
        """
        try:
            # Apple stores GPS in a complex binary format
            # We'll search for specific patterns indicating GPS data
            # Look for patterns that might indicate GPS coordinates
            # Apple often stores these as 8-byte IEEE-754 double-precision values
            lat_pattern = re.compile(b'CNTH.{4,32}?lat[a-z]*', re.DOTALL)
            lon_pattern = re.compile(b'CNTH.{4,32}?lon[a-z]*', re.DOTALL)

            lat_match = lat_pattern.search(mime_data)
            lon_match = lon_pattern.search(mime_data)

            if lat_match and lon_match:
                # Try to find the 8-byte double values after the identifiers
                lat_pos = lat_match.end()
                lon_pos = lon_match.end()

                # Ensure we have enough bytes to extract the doubles
                if len(mime_data) >= lat_pos + 8 and len(mime_data) >= lon_pos + 8:
                    try:
                        latitude = struct.unpack('>d', mime_data[lat_pos:lat_pos + 8])[0]
                        longitude = struct.unpack('>d', mime_data[lon_pos:lon_pos + 8])[0]

                        # Only use if values seem reasonable
                        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                            if "GPSInfo" not in exif_data:
                                exif_data["GPSInfo"] = {}

                            exif_data["GPSInfo"]["GPSLatitude"] = (latitude, 0, 0)
                            exif_data["GPSInfo"]["GPSLongitude"] = (longitude, 0, 0)
                            exif_data["GPSInfo"]["GPSLatitudeRef"] = "N" if latitude >= 0 else "S"
                            exif_data["GPSInfo"]["GPSLongitudeRef"] = "E" if longitude >= 0 else "W"
                    except Exception:
                        # Silently fail if unpacking doesn't work
                        pass
        except Exception as e:
            self.logger.debug(f"Error extracting GPS from Apple MIME data: {e}")

    def _extract_gps_from_apple_makernote(self, maker_note: str) -> Optional[Dict]:
        """
        Extract GPS data from Apple's MakerNote field in EXIF data.

        Args:
            maker_note: Apple MakerNote string
        Returns:
            Dictionary with latitude and longitude if found, None otherwise
        """
        try:
            # Apple MakerNote often contains GPS coordinates in a specific format
            # Look for patterns like decimal numbers that could be coordinates
            coord_pattern = re.compile(r'([-+]?\d+\.\d+)')
            matches = coord_pattern.findall(maker_note)

            if len(matches) >= 2:
                # Try pairs of numbers to see if they could be valid coordinates
                for i in range(len(matches) - 1):
                    try:
                        lat = float(matches[i])
                        lon = float(matches[i + 1])

                        # Check if values are in a reasonable range for coordinates
                        if -90 <= lat <= 90 and -180 <= lon <= 180:
                            return {
                                "latitude": lat,
                                "longitude": lon
                            }
                    except ValueError:
                        continue

            # Search for binary data that might contain GPS info
            if b'bplist' in maker_note.encode('utf-8', errors='ignore'):
                # Apple sometimes stores GPS in binary property lists within MakerNote
                # This is a complex binary format that would require a specialized parser
                # For now, we'll just log that we found a binary plist
                self.logger.debug("Found binary plist in MakerNote, specialized parsing needed")

            return None
        except Exception as e:
            self.logger.debug(f"Error extracting GPS from Apple MakerNote: {e}")
            return None

    async def extract_exif_heif(self, heif_image) -> Optional[Dict]:
        """
        Extract EXIF data from a HEIF/HEIC image using the heif library.

        Args:
            heif_image: HEIF image object
        Returns:
            Dictionary of EXIF data or None if no EXIF data exists
        """
        try:
            # Get EXIF metadata from HEIF image
            exif_data = {}

            # Extract metadata from HEIF
            for metadata in heif_image.metadata or []:
                if metadata.type == 'Exif':
                    # HEIF EXIF data typically starts with a header offset
                    exif_bytes = metadata.data
                    if exif_bytes and len(exif_bytes) > 8:
                        # Skip the EXIF header (usually 8 bytes) to get to the TIFF data
                        exif_stream = BytesIO(exif_bytes)
                        # Try to extract EXIF data from the TIFF-formatted portion
                        try:
                            # Need to process the EXIF data in TIFF format
                            exif_stream.seek(8)  # Skip the Exif\0\0 header
                            exif_image = Image.open(exif_stream)
                            # Extract all EXIF data from the embedded TIFF
                            exif_info = exif_image._getexif() or {}

                            # Process the EXIF data as we do with PIL images
                            gps_info = {}
                            for tag, value in exif_info.items():
                                decoded = TAGS.get(tag, tag)
                                if decoded == "GPSInfo":
                                    for t in value:
                                        sub_decoded = GPSTAGS.get(t, t)
                                        gps_info[sub_decoded] = value[t]
                                    exif_data["GPSInfo"] = gps_info
                                else:
                                    exif_data[decoded] = _make_serialisable(value)
                        except Exception as e:
                            self.logger.debug(f"Error processing HEIF EXIF data: {e}")

                # Apple HEIF files may store GPS in 'mime' type metadata with 'CNTH' format
                elif metadata.type == 'mime':
                    try:
                        # Check for Apple-specific GPS metadata
                        mime_data = metadata.data
                        if b'CNTH' in mime_data:
                            # This is a special Apple container format
                            # Extract GPS data from CNTH container
                            self._extract_apple_gps_from_mime(mime_data, exif_data)
                    except Exception as e:
                        self.logger.debug(f"Error processing Apple MIME metadata: {e}")

            # Extract GPS datetime if available and requested
            if self.extract_geoloc:
                # First try standard GPSInfo
                if "GPSInfo" in exif_data:
                    gps_datetime = self.extract_gps_datetime(exif_data)
                    if gps_datetime.get("latitude") is not None and gps_datetime.get("longitude") is not None:
                        exif_data['gps_info'] = gps_datetime

                # If no GPS found yet, try Apple's MakerNote for GPS data
                has_gps_info = 'gps_info' in exif_data
                has_valid_gps = has_gps_info and exif_data['gps_info'].get('latitude') is not None

                if (not has_gps_info or not has_valid_gps) and 'MakerNote' in exif_data:
                    apple_gps = self._extract_gps_from_apple_makernote(exif_data['MakerNote'])
                    if apple_gps:
                        # If we found GPS data in MakerNote, use it
                        datetime = exif_data.get("DateTimeOriginal") or exif_data.get("DateTime")
                        exif_data['gps_info'] = {
                            "datetime": datetime,
                            "latitude": apple_gps.get("latitude"),
                            "longitude": apple_gps.get("longitude")
                        }

            return _json_safe(exif_data) if exif_data else None

        except Exception as e:
            self.logger.error(f'Error extracting HEIF EXIF data: {e}')
            return None

    async def extract_exif_data(self, image) -> dict:
        """
        Extract EXIF data from the image file object.

        Args:
            image: The PIL Image object.
        Returns:
            Dictionary of EXIF data or empty dict if no EXIF data exists.
        """
        try:
            exif = {}

            if hasattr(image, 'getexif'):
                # For JPEG and some other formats that support _getexif()
                exif_data = image.getexif()
                if exif_data:
                    gps_info = {}
                    for tag, value in exif_data.items():
                        if tag in ExifTags.TAGS:
                            print(f'{ExifTags.TAGS[tag]}:{value}')
                            decoded = TAGS.get(tag, tag)
                            # Convert EXIF data to a readable format
                            exif[decoded] = _make_serialisable(value)
                            if decoded == "GPSInfo":
                                for t in value:
                                    sub_decoded = GPSTAGS.get(t, t)
                                    gps_info[sub_decoded] = value[t]
                                exif["GPSInfo"] = gps_info
                        for ifd_id in IFD:
                            print('>>>>>>>>>', ifd_id.name, '<<<<<<<<<<')
                            try:
                                ifd = exif_data.get_ifd(ifd_id)
                                if ifd_id == IFD.GPSInfo:
                                    resolve = GPSTAGS
                                else:
                                    resolve = TAGS
                                for k, v in ifd.items():
                                    tag = resolve.get(k, k)
                                    print(tag, v)
                                    exif[tag] = _make_serialisable(v)
                            except KeyError:
                                pass
            elif hasattr(image, 'tag') and hasattr(image, 'tag_v2'):
                # For TIFF images which store data in tag and tag_v2 attributes
                # Extract from tag_v2 first (more detailed)
                gps_info = {}
                for tag, value in image.tag_v2.items():
                    tag_name = TAGS.get(tag, tag)
                    if tag_name == "GPSInfo":
                        # For TIFF images, GPS data might be in a nested IFD
                        if isinstance(value, dict):
                            for gps_tag, gps_value in value.items():
                                gps_tag_name = GPSTAGS.get(gps_tag, gps_tag)
                                gps_info[gps_tag_name] = gps_value
                            exif["GPSInfo"] = gps_info
                    else:
                        exif[tag_name] = _make_serialisable(value)

                # Fall back to tag if needed
                if not exif and hasattr(image, 'tag'):
                    for tag, value in image.tag.items():
                        tag_name = TAGS.get(tag, tag)
                        exif[tag_name] = _make_serialisable(value)

            else:
                # For other formats, try to extract directly from image.info
                for key, value in image.info.items():
                    if key.startswith('exif'):
                        # Some formats store EXIF data with keys like 'exif' or 'exif_ifd'
                        if isinstance(value, dict):
                            exif.update(value)
                        elif isinstance(value, bytes):
                            # Try to parse bytes as EXIF data
                            exif_stream = BytesIO(value)
                            try:
                                exif_image = TiffImagePlugin.TiffImageFile(exif_stream)
                                if hasattr(exif_image, 'tag_v2'):
                                    for tag, val in exif_image.tag_v2.items():
                                        tag_name = TAGS.get(tag, tag)
                                        exif[tag_name] = _make_serialisable(val)
                            except Exception as e:
                                self.logger.debug(f"Error parsing EXIF bytes: {e}")
                    else:
                        # Add other metadata
                        exif[key] = _make_serialisable(value)

            # Extract GPS datetime if available
            if self.extract_geoloc and "GPSInfo" in exif:
                gps_datetime = self.extract_gps_datetime(exif)
                if gps_datetime:
                    exif['gps_info'] = gps_datetime

            return _json_safe(exif) if exif else {}
        except (AttributeError, KeyError) as e:
            self.logger.debug(f'Error extracting PIL EXIF data: {e}')
            return {}
        except Exception as e:
            self.logger.error(f'Unexpected error extracting PIL EXIF data: {e}')
            return {}

    async def analyze(self, image: Optional[Image.Image] = None, heif: Any = None, **kwargs) -> dict:
        """
        Extract EXIF data from the given image.

        :param image: PIL Image object (optional)
        :param heif: HEIF image object (optional)
        :return: Dictionary containing EXIF data
        """
        try:
            exif_data = {}

            # Process PIL image if provided
            if image is not None:
                try:
                    pil_exif = await self.extract_exif_data(image)
                    if pil_exif:
                        exif_data.update(pil_exif)
                except Exception as e:
                    self.logger.error(f"Error extracting EXIF from PIL image: {e}")

            # Process HEIF image if provided
            if heif is not None:
                try:
                    heif_exif = await self.extract_exif_heif(heif)
                    if heif_exif:
                        # Update with HEIF data, prioritizing it over PIL data if both exist
                        exif_data.update(heif_exif)
                except Exception as e:
                    self.logger.error(f"Error extracting EXIF from HEIF image: {e}")

            return exif_data
        except Exception as e:
            self.logger.error(f"Error in EXIF analysis: {str(e)}")
            return {}

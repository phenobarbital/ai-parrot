from collections.abc import Mapping, Sequence
from typing import Any, Dict, Optional
import re
import struct
from io import BytesIO
from PIL import Image, ExifTags, PngImagePlugin
from PIL.ExifTags import TAGS, GPSTAGS, IFD
from PIL import TiffImagePlugin
from PIL.TiffImagePlugin import IFDRational
from libxmp import XMPFiles, consts
from pillow_heif import register_heif_opener
from .abstract import ImagePlugin
import base64


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

def get_xmp_modify_date(image, path: Optional[str] = None) -> str | None:
    # 1) Try to grab the raw XMP packet from the JPEG APP1 segment
    raw_xmp = image.info.get("XML:com.adobe.xmp")
    if raw_xmp:
        # 2) Feed it to XMPFiles via a buffer
        xmpfile = XMPFiles(buffer=raw_xmp)
    else:
        # fallback: let XMPFiles pull directly from the file
        # xmpfile = XMPFiles(file_path=path)
        return None

    xmp = xmpfile.get_xmp()
    if not xmp:
        return None

    # 3) Common XMP namespaces & properties for modification history:
    #    - consts.XMP_NS_XMP / "ModifyDate"
    modify = xmp.get_property(consts.XMP_NS_XMP, "ModifyDate")

    xmpfile.close_file()

    return modify


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

    async def extract_iptc_data(self, image) -> dict:
        """
        Extract IPTC metadata from an image.

        Args:
            image: The PIL Image object.
        Returns:
            Dictionary of IPTC data or empty dict if no IPTC data exists.
        """
        try:
            iptc_data = {}

            # Try to get IPTC data from image.info
            if 'photoshop' in image.info:
                photoshop = image.info['photoshop']
                # Extract IPTC information from photoshop data
                iptc_data = self._parse_photoshop_data(photoshop)

            # Try alternate keys for IPTC data in image.info
            elif 'iptc' in image.info:
                iptc = image.info['iptc']
                if isinstance(iptc, bytes):
                    iptc_records = self._parse_iptc_data(iptc)
                    iptc_data.update(iptc_records)
                elif isinstance(iptc, dict):
                    iptc_data.update(iptc)

            # Check for IPTCDigest directly
            if 'IPTCDigest' in image.info:
                iptc_data['IPTCDigest'] = image.info['IPTCDigest']

            # For JPEG images, try to get IPTC from APP13 segment directly
            if not iptc_data and hasattr(image, 'applist'):
                for segment, content in image.applist:
                    if segment == 'APP13' and b'Photoshop 3.0' in content:
                        iptc_data = self._parse_photoshop_data(content)
                        break

            # For TIFF, check for IPTC data in specific tags
            if not iptc_data and hasattr(image, 'tag_v2'):
                # 33723 is the IPTC tag in TIFF
                if 33723 in image.tag_v2:
                    iptc_raw = image.tag_v2[33723]
                    if isinstance(iptc_raw, bytes):
                        iptc_records = self._parse_iptc_data(iptc_raw)
                        iptc_data.update(iptc_records)

                # Check for additional IPTC-related tags in TIFF
                iptc_related_tags = [700, 33723, 34377]  # Various tags that might contain IPTC data
                for tag in iptc_related_tags:
                    if tag in image.tag_v2:
                        tag_name = TAGS.get(tag, f"Tag_{tag}")
                        iptc_data[tag_name] = _make_serialisable(image.tag_v2[tag])

            # For PNG, try to get iTXt or tEXt chunks that might contain IPTC
            if not iptc_data and hasattr(image, 'text'):
                for key, value in image.text.items():
                    if key.startswith('IPTC') or key == 'XML:com.adobe.xmp':
                        iptc_data[key] = value
                    elif key == 'IPTCDigest':
                        iptc_data['IPTCDigest'] = value

            # For XMP metadata in any image format
            if 'XML:com.adobe.xmp' in image.info:
                # Extract IPTCDigest from XMP if present
                xmp_data = image.info['XML:com.adobe.xmp']
                if isinstance(xmp_data, str) and 'IPTCDigest' in xmp_data:
                    # Simple pattern matching for IPTCDigest in XMP
                    match = re.search(r'IPTCDigest="([^"]+)"', xmp_data)
                    if match:
                        iptc_data['IPTCDigest'] = match.group(1)

            return _json_safe(iptc_data) if iptc_data else {}
        except Exception as e:
            self.logger.error(f'Error extracting IPTC data: {e}')
            return {}

    def _parse_photoshop_data(self, data) -> dict:
        """
        Parse Photoshop data block to extract IPTC metadata.

        Args:
            data: Raw Photoshop data (bytes or dict) from APP13 segment.
        Returns:
            Dictionary of extracted IPTC data.
        """
        iptc_data = {}
        try:
            # Handle the case where data is already a dictionary
            if isinstance(data, dict):
                # If it's a dictionary, check for IPTCDigest key directly
                if 'IPTCDigest' in data:
                    iptc_data['IPTCDigest'] = data['IPTCDigest']

                # Check for IPTC data
                if 'IPTC' in data or 1028 in data:  # 1028 (0x0404) is the IPTC identifier
                    iptc_block = data.get('IPTC', data.get(1028, b''))
                    if isinstance(iptc_block, bytes):
                        iptc_records = self._parse_iptc_data(iptc_block)
                        iptc_data.update(iptc_records)

                return iptc_data

            # If it's bytes, proceed with the original implementation
            if not isinstance(data, bytes):
                self.logger.debug(f"Expected bytes for Photoshop data, got {type(data)}")
                return {}

            # Find Photoshop resource markers
            offset = data.find(b'8BIM')
            if offset < 0:
                return {}

            io_data = BytesIO(data)
            io_data.seek(offset)

            while True:
                # Try to read a Photoshop resource block
                try:
                    signature = io_data.read(4)
                    if signature != b'8BIM':
                        break

                    # Resource identifier (2 bytes)
                    resource_id = int.from_bytes(io_data.read(2), byteorder='big')

                    # Skip name: Pascal string padded to even length
                    name_len = io_data.read(1)[0]
                    name_bytes_to_read = name_len + (1 if name_len % 2 == 0 else 0)
                    io_data.read(name_bytes_to_read)

                    # Resource data
                    size = int.from_bytes(io_data.read(4), byteorder='big')
                    padded_size = size + (1 if size % 2 == 1 else 0)

                    resource_data = io_data.read(padded_size)[:size]  # Trim padding if present

                    # Process specific resource types
                    if resource_id == 0x0404:  # IPTC-NAA record (0x0404)
                        iptc_records = self._parse_iptc_data(resource_data)
                        iptc_data.update(iptc_records)
                    elif resource_id == 0x040F:  # IPTCDigest (0x040F)
                        iptc_data['IPTCDigest'] = resource_data.hex()
                    elif resource_id == 0x0425:  # EXIF data (1045)
                        # Already handled by the EXIF extraction but could process here if needed
                        pass

                except Exception as e:
                    self.logger.debug(f"Error parsing Photoshop resource block: {e}")
                    break

            return iptc_data
        except Exception as e:
            self.logger.debug(f"Error parsing Photoshop data: {e}")
            return {}

    def _parse_iptc_data(self, data: bytes) -> dict:
        """
        Parse raw IPTC data bytes.

        Args:
            data: Raw IPTC data bytes.
        Returns:
            Dictionary of extracted IPTC fields.
        """
        iptc_data = {}
        try:
            # IPTC marker (0x1C) followed by record number (1 byte) and dataset number (1 byte)
            i = 0
            while i < len(data):
                # Look for IPTC marker
                if i + 4 <= len(data) and data[i] == 0x1C:
                    record = data[i+1]
                    dataset = data[i+2]

                    # Length of the data field (can be 1, 2, or 4 bytes)
                    if data[i+3] & 0x80:  # Check if the high bit is set
                        # Extended length - 4 bytes
                        if i + 8 <= len(data):
                            length = int.from_bytes(data[i+4:i+8], byteorder='big')
                            i += 8
                        else:
                            break
                    else:
                        # Standard length - 1 byte
                        length = data[i+3]
                        i += 4

                    # Check if we have enough data
                    if i + length <= len(data):
                        field_data = data[i:i+length]

                        # Convert to string if possible
                        try:
                            field_value = field_data.decode('utf-8', errors='replace')
                        except UnicodeDecodeError:
                            field_value = field_data.hex()

                        # Map record:dataset to meaningful names - simplified example
                        key = f"{record}:{dataset}"
                        # Known IPTC fields
                        iptc_fields = {
                            "2:5": "ObjectName",
                            "2:25": "Keywords",
                            "2:80": "By-line",
                            "2:105": "Headline",
                            "2:110": "Credit",
                            "2:115": "Source",
                            "2:120": "Caption-Abstract",
                            "2:122": "Writer-Editor",
                        }

                        field_name = iptc_fields.get(key, f"IPTC_{key}")
                        iptc_data[field_name] = field_value

                        i += length
                    else:
                        break
                else:
                    i += 1

            return iptc_data
        except Exception as e:
            self.logger.debug(f"Error parsing IPTC data: {e}")
            return {}

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
            # Check Modify Date (if any):
            try:
                modify_date = get_xmp_modify_date(image)
                if modify_date:
                    exif["ModifyDate"] = modify_date
            except Exception as e:
                self.logger.debug(f"Error getting XMP ModifyDate: {e}")

            if hasattr(image, 'getexif'):
                # For JPEG and some other formats that support _getexif()
                exif_data = image.getexif()
                if exif_data:
                    gps_info = {}
                    for tag, value in exif_data.items():
                        if tag in ExifTags.TAGS:
                            decoded = TAGS.get(tag, tag)
                            # Convert EXIF data to a readable format
                            if decoded == "UserComment" and isinstance(value, str):
                                try:
                                    # Try to decode base64 UserComment
                                    decoded_value = base64.b64decode(value).decode('utf-8', errors='replace')
                                    exif[decoded] = decoded_value
                                except Exception:
                                    # If decoding fails, use original value
                                    exif[decoded] = _make_serialisable(value)
                            else:
                                exif[decoded] = _make_serialisable(value)
                            if decoded == "GPSInfo":
                                for t in value:
                                    sub_decoded = GPSTAGS.get(t, t)
                                    gps_info[sub_decoded] = value[t]
                                exif["GPSInfo"] = gps_info
                    # Aperture, shutter, flash, lens, tz offset, etc
                    ifd = exif_data.get_ifd(0x8769)
                    for key, val in ifd.items():
                        exif[ExifTags.TAGS[key]] = _make_serialisable(val)
                    for ifd_id in IFD:
                        try:
                            ifd = exif_data.get_ifd(ifd_id)
                            if ifd_id == IFD.GPSInfo:
                                resolve = GPSTAGS
                            else:
                                resolve = TAGS
                            for k, v in ifd.items():
                                tag = resolve.get(k, k)
                                try:
                                    exif[tag] = _make_serialisable(v)
                                except Exception:
                                    exif[tag] = v
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

            # Process HEIF image if provided (prioritize over PIL)
            if heif is not None:
                try:
                    heif_exif = await self.extract_exif_heif(heif)
                    if heif_exif:
                        # Update with HEIF data, prioritizing it over PIL data if both exist
                        exif_data.update(heif_exif)
                except Exception as e:
                    self.logger.error(f"Error extracting EXIF from HEIF image: {e}")

            # Process PIL image if provided
            if image is not None:
                try:
                    pil_exif = await self.extract_exif_data(image)
                    if pil_exif:
                        exif_data.update(pil_exif)
                except Exception as e:
                    self.logger.error(f"Error extracting EXIF from PIL image: {e}")

                # Extract IPTC data
                try:
                    pil_iptc = await self.extract_iptc_data(image)
                    if pil_iptc:
                        exif_data.update(pil_iptc)
                except Exception as e:
                    self.logger.error(
                        f"Error extracting IPTC data from PIL image: {e}"
                    )


            return exif_data
        except Exception as e:
            self.logger.error(f"Error in EXIF analysis: {str(e)}")
            return {}

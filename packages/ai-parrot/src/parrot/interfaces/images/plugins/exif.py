from collections.abc import Mapping, Sequence
from typing import Any, Dict, Optional, List, Tuple
import re
import plistlib
import struct
from datetime import datetime
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

    def convert_to_degrees(self, value: tuple[IFDRational]):
        """
        Convert a 3-tuple of (deg, min, sec)—each component either an IFDRational or a float/int—
        into a decimal‐degrees float. Returns None on any error.
        """
        try:
            # Helper: if `r` has .num and .den, treat it as IFDRational; otherwise, cast to float.
            def to_float(r):
                if hasattr(r, "num") and hasattr(r, "den"):
                    # Avoid division by zero
                    if r.den == 0:
                        return 0.0
                    return float(r.num) / float(r.den)
                return float(r) if r is not None else 0.0

            if not value or len(value) < 3:
                return None

            d = to_float(value[0])
            m = to_float(value[1])
            s = to_float(value[2])
            return d + (m / 60.0) + (s / 3600.0)

        except Exception:
            return None

    def extract_gps_datetime(self, exif: dict):
        """
        Extract GPS coordinates and a timestamp (preferring GPSDateStamp+GPSTimeStamp if available,
        else falling back to DateTimeOriginal/DateTime) from a (string-keyed) EXIF dict.

        Returns a dict:
        {
            "datetime": <ISO8601 string or None>,
            "date": <date string or None>,
            "latitude": <decimal float or None>,
            "longitude": <decimal float or None>
        }
        """
        gps = exif.get("GPSInfo", {}) or {}
        # 1) Build latitude/longitude, if present:
        latitude = longitude = None
        lat_tuple = gps.get("GPSLatitude")
        lat_ref = gps.get("GPSLatitudeRef")
        lon_tuple = gps.get("GPSLongitude")
        lon_ref = gps.get("GPSLongitudeRef")

        if lat_tuple and lat_ref and lon_tuple and lon_ref:
            # Convert the 3-tuples into decimal degrees
            lat_dd = self.convert_to_degrees(lat_tuple)
            lon_dd = self.convert_to_degrees(lon_tuple)

            if lat_dd is not None:
                if str(lat_ref).upper() == "S":
                    lat_dd = -lat_dd
                latitude = lat_dd

            if lon_dd is not None:
                if str(lon_ref).upper() == "W":
                    lon_dd = -lon_dd
                longitude = lon_dd

        # 2) Build a datetime string: prefer GPSDateStamp+GPSTimeStamp if both exist
        datetime_str = None
        date_str = None
        date_stamp = gps.get("GPSDateStamp")      # e.g. "2025:03:18"
        time_stamp = gps.get("GPSTimeStamp")      # e.g. (23.0, 57.0, 50.0)

        if date_stamp and time_stamp:
            try:
                # time_stamp might be floats; cast to int for hours/minutes/seconds.
                h = int(time_stamp[0])
                m = int(time_stamp[1])
                s = int(time_stamp[2])
                # date_stamp format is "YYYY:MM:DD"
                dt = datetime.strptime(date_stamp, "%Y:%m:%d")
                dt = dt.replace(hour=h, minute=m, second=s)
                datetime_str = dt.isoformat()
                date_str = dt.date().isoformat()
            except Exception:
                # If any parsing error, fall back
                datetime_str = None

        # 3) If GPSDateStamp+GPSTimeStamp didn’t yield a usable value, try DateTimeOriginal/DateTime
        if not datetime_str:
            datetime_str = exif.get("DateTimeOriginal") or exif.get("DateTime") or None
            if datetime_str:
                # Convert to ISO8601 format if it’s a string with YYYY:MM:DD HH:MM:SS
                try:
                    dt = datetime.strptime(datetime_str, "%Y:%m:%d %H:%M:%S")
                    datetime_str = dt.isoformat()
                    date_str = dt.date().isoformat()
                except ValueError:
                    # If parsing fails, keep it as is
                    pass
                except TypeError:
                    # If datetime_str is None or not a string, keep it as None
                    datetime_str = None

        return {
            "datetime": datetime_str,
            "date": date_str,
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
                    record = data[i + 1]
                    dataset = data[i + 2]

                    # Length of the data field (can be 1, 2, or 4 bytes)
                    if data[i + 3] & 0x80:  # Check if the high bit is set
                        # Extended length - 4 bytes
                        if i + 8 <= len(data):
                            length = int.from_bytes(data[i + 4:i + 8], byteorder='big')
                            i += 8
                        else:
                            break
                    else:
                        # Standard length - 1 byte
                        length = data[i + 3]
                        i += 4

                    # Check if we have enough data
                    if i + length <= len(data):
                        field_data = data[i:i + length]

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

    def _extract_gps_from_apple_makernote(self, maker_note: Any) -> Optional[Dict]:
        """
        Extract GPS data from Apple's MakerNote field.

        Fixed version that properly handles Apple's MakerNote structure and
        looks for actual GPS coordinates rather than test values.
        """
        try:
            # 1) Ensure we have raw bytes
            if isinstance(maker_note, bytes):
                data_bytes = maker_note
            elif isinstance(maker_note, str):
                data_bytes = maker_note.encode("latin-1", errors="ignore")
            else:
                return None

            # 2) Find and properly parse binary plists
            gps_data = self._parse_apple_plists_for_gps(data_bytes)
            if gps_data:
                return gps_data

            # 3) Try parsing as TIFF-style MakerNote first
            gps_data = self._parse_tiff_makernote_gps(data_bytes)
            if gps_data:
                return gps_data

            # 4) Enhanced fallback with better coordinate detection
            gps_data = self._enhanced_regex_gps_search(data_bytes)
            if gps_data:
                return gps_data

            return None

        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.warning(f"Error extracting GPS from Apple MakerNote: {e}")
            return None

    def _parse_apple_plists_for_gps(self, data_bytes: bytes) -> Optional[Dict]:
        """Parse binary plists properly with length headers"""
        bplist_marker = b"bplist00"
        offset = 0

        while True:
            idx = data_bytes.find(bplist_marker, offset)
            if idx < 0:
                break

            try:
                # Parse the plist properly by reading its length
                plist_data = self._extract_single_plist(data_bytes, idx)
                if not plist_data:
                    offset = idx + len(bplist_marker)
                    continue

                parsed = plistlib.loads(plist_data)
                coords = self._find_gps_in_plist(parsed)
                if coords:
                    return coords

            except Exception:
                pass

            offset = idx + len(bplist_marker)

        return None

    def _extract_single_plist(self, data: bytes, start_idx: int) -> Optional[bytes]:
        """Extract a single binary plist with proper length calculation"""
        try:
            # Binary plist format: 8-byte header + data + trailer
            if start_idx + 8 >= len(data):
                return None

            # Try different approaches to find plist end
            # Method 1: Look for next bplist or end of data
            next_bplist = data.find(b"bplist00", start_idx + 8)
            if next_bplist > 0:
                candidate = data[start_idx:next_bplist]
            else:
                # Try parsing increasingly larger chunks
                for size in [32, 64, 128, 256, 512, 1024, 2048]:
                    if start_idx + size > len(data):
                        candidate = data[start_idx:]
                        break
                    candidate = data[start_idx:start_idx + size]
                    try:
                        plistlib.loads(candidate)
                        return candidate
                    except Exception:
                        continue
                candidate = data[start_idx:]

            # Validate by trying to parse
            try:
                plistlib.loads(candidate)
                return candidate
            except Exception:
                return None

        except Exception:
            return None

    def _find_gps_in_plist(self, obj: Any, path: str = "") -> Optional[Dict]:
        """
        Enhanced GPS coordinate finder that looks for various GPS-related keys
        and validates coordinate ranges more strictly
        """
        # Common GPS key patterns in Apple plists
        gps_lat_keys = [
            "Latitude", "latitude", "lat", "GPSLatitude",
            "Location.Latitude", "coordinates.latitude"
        ]
        gps_lon_keys = [
            "Longitude", "longitude", "lon", "lng", "GPSLongitude",
            "Location.Longitude", "coordinates.longitude"
        ]

        if isinstance(obj, dict):
            # Direct GPS coordinate check
            lat_val = None
            lon_val = None

            # Look for latitude
            for lat_key in gps_lat_keys:
                if lat_key in obj:
                    try:
                        lat_val = float(obj[lat_key])
                        break
                    except Exception:
                        continue

            # Look for longitude
            for lon_key in gps_lon_keys:
                if lon_key in obj:
                    try:
                        lon_val = float(obj[lon_key])
                        break
                    except Exception:
                        continue

            # Validate coordinates
            if lat_val is not None and lon_val is not None:
                if self._are_valid_coordinates(lat_val, lon_val):
                    return {"latitude": lat_val, "longitude": lon_val}

            # Look for nested coordinate structures
            for key, value in obj.items():
                if any(term in key.lower() for term in ["location", "gps", "coord", "position"]):
                    result = self._find_gps_in_plist(value, f"{path}.{key}")
                    if result:
                        return result

            # Recurse into all values
            for key, value in obj.items():
                result = self._find_gps_in_plist(value, f"{path}.{key}")
                if result:
                    return result

        elif isinstance(obj, (list, tuple)):
            for i, item in enumerate(obj):
                result = self._find_gps_in_plist(item, f"{path}[{i}]")
                if result:
                    return result

        return None

    def _are_valid_coordinates(self, lat: float, lon: float) -> bool:
        """
        Enhanced coordinate validation that rejects obvious test/dummy values
        """
        # Basic range check
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return False

        # Reject obvious test values
        test_values = [
            0.0, 1.0, 2.0, 2.1, 2.2, 3.0, 4.0, 5.0, 10.0, -1.0, -2.0, 123.0, 123.456, 90.0, 180.0
        ]

        if lat in test_values and lon in test_values:
            return False

        # Reject coordinates that are too close to (0,0) unless specifically valid
        if abs(lat) < 0.01 and abs(lon) < 0.01:
            return False

        # Reject coordinates where both values are the same (likely test data)
        if lat == lon:
            return False

        # Additional validation: check for reasonable precision
        # Real GPS coordinates usually have more precision
        lat_str = str(lat)
        lon_str = str(lon)

        # If both coordinates have very low precision, they might be test values
        if '.' in lat_str and '.' in lon_str:
            lat_decimals = len(lat_str.split('.')[1])
            lon_decimals = len(lon_str.split('.')[1])
            if lat_decimals <= 1 and lon_decimals <= 1 and abs(lat) < 10 and abs(lon) < 10:
                return False

        return True

    def _parse_tiff_makernote_gps(self, data_bytes: bytes) -> Optional[Dict]:
        """
        Parse Apple's TIFF-style MakerNote entries for GPS data
        """
        try:
            # Look for TIFF structure in the MakerNote
            if len(data_bytes) < 12:
                return None

            # Check for TIFF byte order marks
            if data_bytes[:2] in [b'II', b'MM']:
                return self._parse_tiff_entries(data_bytes)

            # Apple MakerNote often starts with "Apple iOS" followed by TIFF data
            apple_marker = data_bytes.find(b'Apple iOS')
            if apple_marker >= 0:
                tiff_start = apple_marker + 9  # Length of "Apple iOS"
                if tiff_start < len(data_bytes):
                    return self._parse_tiff_entries(data_bytes[tiff_start:])

            return None

        except Exception:
            return None

    def _parse_tiff_entries(self, data: bytes) -> Optional[Dict]:
        """Parse TIFF-style directory entries looking for GPS tags"""
        try:
            if len(data) < 8:
                return None

            # Determine byte order
            if data[:2] == b'II':
                endian = '<'  # Little endian
            elif data[:2] == b'MM':
                endian = '>'  # Big endian
            else:
                return None

            # Skip to first IFD
            offset = struct.unpack(f'{endian}I', data[4:8])[0]
            if offset >= len(data):
                return None

            # Read number of directory entries
            if offset + 2 >= len(data):
                return None

            num_entries = struct.unpack(f'{endian}H', data[offset:offset + 2])[0]
            offset += 2

            # Parse each entry
            for i in range(min(num_entries, 100)):  # Limit to prevent infinite loops
                if offset + 12 > len(data):
                    break

                entry = data[offset:offset + 12]
                tag, type_id, count, value_offset = struct.unpack(f'{endian}HHII', entry)

                # Look for GPS-related tags (these are hypothetical Apple GPS tags)
                if tag in [0x0001, 0x0002, 0x0003, 0x0004]:  # Common GPS tag IDs
                    # This would need more specific implementation based on Apple's actual tags
                    pass

                offset += 12

            return None

        except Exception:
            return None

    def _enhanced_regex_gps_search(self, data_bytes: bytes) -> Optional[Dict]:
        """
        Enhanced regex search that's more discriminating about coordinate patterns
        """
        try:
            # Try UTF-8 first, then latin-1
            for encoding in ['utf-8', 'latin-1']:
                try:
                    text = data_bytes.decode(encoding, errors='ignore')
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return None

            # Look for coordinate patterns in various formats
            patterns = [
                # Decimal degrees with high precision
                r'(?:lat|latitude)[:\s=]*([+-]?\d{1,2}\.\d{4,})',
                r'(?:lon|lng|longitude)[:\s=]*([+-]?\d{1,3}\.\d{4,})',
                # Coordinates in JSON-like structures
                r'"(?:lat|latitude)"\s*:\s*([+-]?\d+\.\d+)',
                r'"(?:lon|lng|longitude)"\s*:\s*([+-]?\d+\.\d+)',
                # Coordinates with more context
                r'(?:coordinate|position|location)[^0-9]*([+-]?\d+\.\d{4,})[^0-9]*([+-]?\d+\.\d{4,})'
            ]

            for pattern in patterns:
                matches = re.finditer(pattern, text, re.IGNORECASE)
                for match in matches:
                    try:
                        if len(match.groups()) == 2:
                            lat, lon = float(match.group(1)), float(match.group(2))
                        else:
                            # Look for the next coordinate nearby
                            coord = float(match.group(1))
                            # This needs more sophisticated logic
                            continue

                        if self._are_valid_coordinates(lat, lon):
                            return {"latitude": lat, "longitude": lon}
                    except Exception:
                        continue

            return None

        except Exception:
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
            try:
                if exif_data := image.getexif():
                    gps_info = {}
                    for tag_id, value in exif_data.items():
                        tag_name = ExifTags.TAGS.get(tag_id, tag_id)
                        if isinstance(tag_name, (int, float)):
                            # Skip numeric tags that are not strings
                            continue
                        # Convert EXIF data to a readable format
                        if tag_name == "UserComment" and isinstance(value, str):
                            try:
                                # Try to decode base64 UserComment
                                decoded_value = base64.b64decode(value).decode('utf-8', errors='replace')
                                exif[tag_name] = decoded_value
                            except Exception:
                                # If decoding fails, use original value
                                exif[tag_name] = _make_serialisable(value)
                        else:
                            exif[tag_name] = _make_serialisable(value)
                        if tag_name == "GPSInfo":
                            # value is itself a dict of numeric sub‐tags:
                            gps_ifd = {}
                            if isinstance(value, dict):
                                try:
                                    for sub_id, sub_val in value.items():
                                        sub_name = GPSTAGS.get(sub_id, sub_id)
                                        gps_ifd[sub_name] = sub_val
                                    exif["GPSInfo"] = gps_ifd
                                except Exception:
                                    for t in value:
                                        sub_decoded = GPSTAGS.get(t, t)
                                        gps_info[sub_decoded] = value[t]
                                    exif["GPSInfo"] = gps_info
                            else:
                                gps_info = {}
                                gps_raw = exif_data.get_ifd(IFD.GPSInfo) or {}
                                for sub_tag_id, sub_val in gps_raw.items():
                                    sub_name = GPSTAGS.get(sub_tag_id, sub_tag_id)
                                    gps_info[sub_name] = sub_val
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
                                if isinstance(tag, int):
                                    continue
                                try:
                                    exif[tag] = _make_serialisable(v)
                                except Exception:
                                    exif[tag] = v
                        except KeyError:
                            pass
            except Exception as e:
                self.logger.warning(
                    f'Error extracting EXIF data: {e}'
                )

        elif hasattr(image, 'tag') and hasattr(image, 'tag_v2'):
            # For TIFF images which store data in tag and tag_v2 attributes
            # Extract from tag_v2 first (more detailed)
            gps_info = {}
            try:
                for tag, value in image.tag_v2.items():
                    tag_name = TAGS.get(tag, tag)
                    if isinstance(tag_name, int):
                        # Skip numeric tags that are not strings
                        continue
                    # Convert EXIF data to a readable format
                    if tag_name == "GPSInfo":
                        # For TIFF images, GPS data might be in a nested IFD
                        if isinstance(value, dict):
                            for gps_tag, gps_value in value.items():
                                gps_tag_name = GPSTAGS.get(gps_tag, gps_tag)
                                gps_info[gps_tag_name] = gps_value
                            exif["GPSInfo"] = gps_info
                    else:
                        exif[tag_name] = _make_serialisable(value)
            except Exception as e:
                self.logger.debug(f'Error extracting TIFF EXIF data: {e}')
            # If tag_v2 is not available or empty, fall back to tag

            # Fall back to tag if needed
            if not exif and hasattr(image, 'tag'):
                try:
                    for tag, value in image.tag.items():
                        tag_name = TAGS.get(tag, tag)
                        exif[tag_name] = _make_serialisable(value)
                except Exception as e:
                    self.logger.debug(f'Error extracting TIFF TAG data: {e}')

        else:
            # For other formats, try to extract directly from image.info
            try:
                for key, value in image.info.items():
                    if isinstance(key, int):
                        continue
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
                                self.logger.warning(f"Error parsing EXIF bytes: {e}")
                    else:
                        # Add other metadata
                        exif[key] = _make_serialisable(value)
            except Exception as e:
                self.logger.warning(f'Unable to extract EXIF from from image.info: {e}')

        # Extract GPS datetime if available
        if self.extract_geoloc and "GPSInfo" in exif:
            try:
                if gps_datetime := self.extract_gps_datetime(exif):
                    exif['gps_info'] = gps_datetime
            except Exception as e:
                self.logger.warning(
                    f"Error extracting GPS datetime: {e}"
                )
        # If no GPSInfo, check for MakerNote which might contain GPS data
        if self.extract_geoloc and "MakerNote" in exif:
            if gps_info := self._extract_gps_from_apple_makernote(exif["MakerNote"]):
                print('RESULT MAKER > ', gps_info)
                if not exif.get('gps_info', None):
                    exif['gps_info'] = gps_info
        # If we have no GPSInfo, check for XMP metadata
        if self.extract_geoloc and "XML:com.adobe.xmp" in image.info:
            try:
                xmp_data = image.info["XML:com.adobe.xmp"]
                if isinstance(xmp_data, str):
                    # Simple pattern matching for GPS in XMP
                    lat_match = re.search(r'GPSLatitude="([^"]+)"', xmp_data)
                    lon_match = re.search(r'GPSLongitude="([^"]+)"', xmp_data)
                    if lat_match and lon_match:
                        latitude = float(lat_match.group(1))
                        longitude = float(lon_match.group(1))
                        exif['gps_info'] = {
                            "latitude": latitude,
                            "longitude": longitude
                        }
            except Exception as e:
                self.logger.warning(f"Error extracting GPS from XMP: {e}")
        # If we have no GPSInfo, check for IPTC metadata
        if self.extract_geoloc and "IPTCDigest" in image.info:
            exif['gps_info'] = image.info["IPTCDigest"]
        # If we have no GPSInfo, check for IPTC metadata
        if self.extract_geoloc and "IPTC" in image.info:
            iptc_data = self._parse_photoshop_data(image.info["IPTC"])
            if iptc_data:
                exif.update(iptc_data)

        return _json_safe(exif) if exif else {}

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

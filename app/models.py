"""Pydantic models for config and API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class AzuracastStation(BaseModel):
    """One Azuracast station config."""
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    station_shortcode: str = ""


class MetadataProvider(BaseModel):
    """Artist/metadata provider (e.g. Last.fm, MusicBrainz)."""
    name: str = ""
    api_key_or_token: str = ""
    base_url: str = ""


class FFmpegSettings(BaseModel):
    """Global FFmpeg/HLS settings (paths and segmenter options)."""
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    hls_time: int = 2
    hls_list_size: int = 4
    hls_segmenter_idle_timeout_seconds: int = 0


class FFmpegProfile(BaseModel):
    """Named FFmpeg encoding profile. id is stable so channels stay linked after renames."""
    id: str = ""
    name: str = ""
    preset_name: str = "custom"

    @model_validator(mode="before")
    @classmethod
    def set_id_from_name(cls, data: Any) -> Any:
        """Ensure id is set when loading from JSON so existing config works."""
        if isinstance(data, dict) and not (data.get("id") or "").strip():
            data = {**data, "id": (data.get("name") or "").strip() or "default"}
        return data
    video_codec: str = "libx264"
    video_bitrate: str = "2M"
    preset: str = "medium"
    pixel_format: str = "yuv420p"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    hardware_accel: bool = False
    hw_accel_type: str = "none"
    hw_accel_device: str = ""
    extra_args: list[str] = Field(default_factory=list)
    thread_count: int = 0
    video_profile: str = ""
    video_buffer_size: str = ""
    allow_bframes: bool = True
    audio_channels: int = 0
    sample_rate: str = ""
    normalize_loudness: str = "off"
    normalize_audio: bool = False
    normalize_video: bool = False


class OverlayPlacement(BaseModel):
    """Position/size of one overlay element on a background."""
    key: str
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    font_size: int = 24
    anchor: str = "nw"
    font_color: str = "white"
    shadow_color: str = "black"
    font_family: str = ""
    font_style: str = "normal"
    scroll_speed: int = 0
    hidden: bool = False


class BackgroundTemplate(BaseModel):
    """A background definition (stock or custom)."""
    id: str = ""
    name: str = ""
    is_stock: bool = True
    image_path: str = ""
    overlay_placements: list[OverlayPlacement] = Field(default_factory=list)


class Channel(BaseModel):
    """One music channel."""
    id: str = ""
    name: str = ""
    slug: str = ""
    azuracast_station_id: str = ""
    ffmpeg_profile_id: str = ""
    background_id: str = "stock"
    stream_port: int = 0
    enabled: bool = True
    # Guide number for XMLTV/HDHomeRun lineup. None = auto (800, 801, ...).
    guide_number: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class AdminState(BaseModel):
    """Full administration state (saved to data dir)."""
    azuracast_stations: list[AzuracastStation] = Field(default_factory=list)
    metadata_providers: list[MetadataProvider] = Field(default_factory=list)
    ffmpeg_profiles: list[FFmpegProfile] = Field(default_factory=list)
    ffmpeg_settings: FFmpegSettings | None = None
    channels: list[Channel] = Field(default_factory=list)
    service_started: bool = False
    hdhr_uuid: str = ""
    hdhr_tuner_count: int = 4

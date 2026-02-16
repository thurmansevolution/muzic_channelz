"""Pydantic models for config and API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


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


class FFmpegProfile(BaseModel):
    """Named FFmpeg encoding profile."""
    name: str = ""
    preset_name: str = "custom"
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
    extra: dict[str, Any] = Field(default_factory=dict)


class AdminState(BaseModel):
    """Full administration state (saved to data dir)."""
    azuracast_stations: list[AzuracastStation] = Field(default_factory=list)
    metadata_providers: list[MetadataProvider] = Field(default_factory=list)
    ffmpeg_profiles: list[FFmpegProfile] = Field(default_factory=list)
    channels: list[Channel] = Field(default_factory=list)
    service_started: bool = False

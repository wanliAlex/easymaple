"""Cache management for storing last loaded files."""

import json
import os
from src.easymaple.common import config


CACHE_FILE = os.path.join(config.RESOURCES_DIR, '.cache.json')


def load_cache():
    """Load cache from file, return empty dict if not found."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_cache(cache_data):
    """Save cache data to file."""
    try:
        # Ensure resources directory exists
        os.makedirs(config.RESOURCES_DIR, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f, indent=2)
    except IOError:
        pass  # Fail silently if can't save cache


def get_last_command_book():
    """Get path to last loaded command book."""
    cache = load_cache()
    return cache.get('last_command_book')


def set_last_command_book(file_path):
    """Save path to last loaded command book."""
    cache = load_cache()
    cache['last_command_book'] = file_path
    save_cache(cache)


def get_last_routine():
    """Get path to last loaded routine."""
    cache = load_cache()
    return cache.get('last_routine')


def set_last_routine(file_path):
    """Save path to last loaded routine."""
    cache = load_cache()
    cache['last_routine'] = file_path
    save_cache(cache)


def auto_load_last_files():
    """Attempt to load last used command book and routine."""
    cache = load_cache()
    
    command_book_loaded = False
    
    # Try to load last command book
    last_command_book = cache.get('last_command_book')
    if last_command_book and os.path.exists(last_command_book):
        try:
            if config.bot:
                config.bot.load_commands(last_command_book)
                print(f"[Cache] Auto-loaded command book: {os.path.basename(last_command_book)}")
                command_book_loaded = True
        except Exception as e:
            print(f"[Cache] Failed to auto-load command book: {e}")
    
    # Try to load last routine (only if command book was loaded successfully)
    if command_book_loaded:
        last_routine = cache.get('last_routine')
        if last_routine and os.path.exists(last_routine):
            try:
                if config.routine:
                    config.routine.load(last_routine)
                    print(f"[Cache] Auto-loaded routine: {os.path.basename(last_routine)}")
            except Exception as e:
                print(f"[Cache] Failed to auto-load routine: {e}")
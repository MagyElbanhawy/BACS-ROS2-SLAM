from setuptools import setup

setup(
    name="bacs_scheduler",
    version="1.1.0",
    packages=["bacs_scheduler"],
    data_files=[("share/ament_index/resource_index/packages", ["resource/bacs_scheduler"]),
                ("share/bacs_scheduler", ["package.xml"])],
    install_requires=["setuptools", "pyserial", "numpy", "scipy"],
    entry_points={"console_scripts": [
        "bacs_sender = bacs_scheduler.sender_node:main",
        "bacs_receiver = bacs_scheduler.receiver_node:main",
        "bacs_candidates = bacs_scheduler.candidate_node:main",
    ]},
)

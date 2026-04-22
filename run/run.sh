#!/bin/bash
echo "Activating conda environment..."
source /home/lauretta/anaconda3/etc/profile.d/conda.sh
conda activate base
echo "Running Hearthlight..."
cd /home/lauretta/dhs-passenger-detection && /home/lauretta/anaconda3/bin/python -m hearthlight start --interactive
echo "Python script has finished. Press enter to exit."
read  # Waits for user input before closing the terminal.

module Main (main) where

import App (add)
import Control.Monad (unless)
import System.Exit (exitFailure)

main :: IO ()
main = unless (add 1 2 == 3) exitFailure

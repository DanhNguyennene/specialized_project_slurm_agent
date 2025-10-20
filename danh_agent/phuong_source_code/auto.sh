test_clean ()
{
	: > /home/omni/phuongTran/Test/log/testAgent.1;
	: > /home/omni/phuongTran/Test/log/testResult.txt;
}

test_"$1"

